# Free Trial & Tutorial/Profile Delivery — Design Spec

Date: 2026-09-15
Status: proposed
Parent spec: `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` (§2.3, §3, §4, §9,
§14 — this spec implements the trial feature and tutorial infrastructure
that parent spec deferred to "a future plan")

## 1. Summary

Two things, built together because the first is useless without the second:

1. **Free Trial flow** — one 24-hour, 1GB trial VPN account per Telegram
   user, lifetime limit, bound to the reserved `Trial-Iran` IBSng group.
   Triggered from the main menu's 🎁 Free Trial button (currently a
   placeholder).
2. **Tutorial & connection-profile delivery** — the infrastructure that
   sends a buyer their OpenVPN profile, a step-by-step setup guide, an
   app download link, and their account credentials after any
   provisioning event. Trial is the first (and for now, only) caller of
   this, but it's built to be reused unchanged by the Buy/Renew flows
   (a later sub-project) — same as AloBot's `deliver_platform_protocol_setup`
   is shared by its trial and purchase flows today.

Ported from AloBot's proven mechanics (`/Users/peyman/telegram-bot`), simplified
wherever Homeland's simpler catalog (no categories-as-a-matrix, no fixed
locations, no Cisco protocol) makes AloBot's equivalent machinery
unnecessary.

## 2. What's simpler than AloBot, and why

- **No trial "tier" system.** AloBot's trial account can land in one of
  three dedicated groups (`normal`/`prime`/`junior` tiers), assigned by
  an admin via `/settrial`, decoupled from the category the user picks
  in the flow. Homeland has exactly one trial group (`Trial-Iran`),
  already bound to the `Plan` row seeded in the catalog migration
  (category `"trial"`) — the trial flow just looks that `Plan` up, no
  separate tier-assignment admin mechanism needed.
- **No category/location step before creation.** AloBot's trial flow
  asks category (and location, for "fixed") before the account is
  created, because that determines the actual IBSng group (via tier).
  Homeland's trial always uses the one `Trial-Iran` group regardless of
  anything the user picks — so the flow goes straight from "confirm" to
  account creation, and the only picker involved is protocol/platform
  for content-delivery purposes afterward.
- **No category-based protocol eligibility.** AloBot excludes Cisco
  AnyConnect outside its "normal" category. Homeland offers exactly two
  protocols (L2TP, OpenVPN) on every plan (parent spec §9) — no
  category-conditional exclusion needed.
- **No location dimension on guides/profiles.** AloBot's `TutorialGuide`
  and `OpenVpnProfile` both carry a `location_id` for its fixed-location
  category. Homeland has no locations at all (parent spec §2.2) — drop
  that column/dimension entirely.
- **OpenVPN gets one shared guide, not a per-platform one.** Per parent
  spec §9, L2TP gets 4 platform-specific guides (iOS/Android/Windows/
  macOS); OpenVPN gets exactly 1 (the OpenVPN Connect app works the same
  way across platforms). So the flow asks **protocol first**, and only
  asks platform if the answer is L2TP — inverted from AloBot's
  platform-first ordering, and one fewer screen for OpenVPN users.
- **Download links live in `AppConfig`, not a new table.** AloBot has a
  dedicated `download_links` table keyed by (platform, protocol) for a
  matrix of app-store URLs. Homeland only ever needs a handful of
  static URLs (OpenVPN Connect on iOS/Android/Windows/macOS) — plain
  `AppConfig` keys (`download_link:openvpn:ios`, etc.) are enough, reusing
  infrastructure that already exists rather than adding a table for a
  handful of rows that rarely change.
- **What's ported unchanged:** bot-generated credential format (prefix +
  random suffix username, mixed-alphanumeric random password), the
  single shared `create_vpn_user` function (no separate trial-vs-paid
  creation path), the `file_id`-replay storage model for guides/profiles
  (admin uploads once, Telegram serves forever), the Android+L2TP
  compatibility guard (a real OS constraint — Android 12+ dropped
  built-in L2TP/IPsec — not an AloBot-specific business rule), and the
  overall delivery sequence (profile → guide → download link → credentials
  message).

## 3. Data models

```python
class TutorialPlatform(Base):
    __tablename__ = "tutorial_platforms"
    id: Mapped[int]
    label: Mapped[str]           # "iOS", "Android", "Windows", "macOS"
    is_active: Mapped[bool]
    sort_order: Mapped[int]

class TutorialProtocol(Base):
    __tablename__ = "tutorial_protocols"
    id: Mapped[int]
    label: Mapped[str]           # "L2TP", "OpenVPN"
    is_active: Mapped[bool]
    sort_order: Mapped[int]

class TutorialGuide(Base):
    __tablename__ = "tutorial_guides"
    # unique on (platform_id, protocol_id) - no category/location dimension,
    # unlike AloBot's guide (Homeland has neither axis)
    id: Mapped[int]
    platform_id: Mapped[int]     # FK tutorial_platforms.id
    protocol_id: Mapped[int]     # FK tutorial_protocols.id
    body_html: Mapped[str | None]     # optional caption, file-based guides usually skip this
    media_file_id: Mapped[str | None]
    media_type: Mapped[str | None]    # "photo" | "document" | "video"
    is_active: Mapped[bool]
    sort_order: Mapped[int]

class OpenVpnProfile(Base):
    __tablename__ = "openvpn_profiles"
    # platform_id NULL = generic profile, matches any platform;
    # a platform-specific row (if any) wins over the generic one.
    id: Mapped[int]
    name: Mapped[str]
    platform_id: Mapped[int | None]   # FK tutorial_platforms.id, nullable
    file_id: Mapped[str | None]
    file_type: Mapped[str | None]     # "document" | "photo" | "video"
    text: Mapped[str | None]          # inline config text, if no file uploaded
    is_active: Mapped[bool]
    created_at: Mapped[dt.datetime]
```

`VPNUser` gains `is_trial: Mapped[bool] = mapped_column(Boolean, default=False)`
— the only column needed for eligibility (§5). No `service_id`-equivalent
is needed yet since Buy/Renew (which would set `plan_id`, already present
on `VPNUser` from the bootstrap slice) isn't built; trial rows just set
`plan_id` to the Trial plan's id.

## 4. Credential generation & account creation

```python
# app/services/vpn_users.py (new file)
_CREDENTIAL_CHARS = string.ascii_lowercase + string.digits
_USERNAME_PREFIX = "hl."
_USERNAME_SUFFIX_LEN = 6
_PASSWORD_LEN = 6

def generate_vpn_credentials() -> tuple[str, str]:
    """Ported from AloBot's generate_vpn_credentials - same shape, this
    project's own prefix. Password is rejection-sampled to guarantee at
    least one letter and one digit (a pure random draw over a mixed
    charset can otherwise land all-letters or all-digits)."""
    suffix = "".join(secrets.choice(_CREDENTIAL_CHARS) for _ in range(_USERNAME_SUFFIX_LEN))
    return f"{_USERNAME_PREFIX}{suffix}", _random_password(_PASSWORD_LEN)


async def create_vpn_user(
    session: AsyncSession, client: IBSngClient, *,
    telegram_id: int, username: str, password: str, group_name: str,
    data_cap_mb: int, plan_id: int | None = None, is_trial: bool = False,
) -> VPNUser:
    """The ONE account-creation path - trial and (later) paid purchases
    both call this, differentiated only by is_trial/plan_id. Mirrors
    AloBot's create_vpn_user exactly: local uniqueness pre-check ->
    IBSng account creation -> local row insert -> IntegrityError as a
    race-condition backstop (covers both a username collision AND, via
    the partial unique index in §5, a duplicate trial claim)."""
    existing = await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
    if existing.scalar_one_or_none() is not None:
        raise VPNUsernameTakenError(f"{username!r} already exists locally")

    await client.create_user(username=username, password=password, group_name=group_name, credit=data_cap_mb)

    vpn_user = VPNUser(
        telegram_id=telegram_id, ibsng_username=username, ibsng_group=group_name,
        plan_id=plan_id, data_cap_mb=data_cap_mb, is_trial=is_trial,
    )
    session.add(vpn_user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise VPNUsernameTakenError(f"{username!r} lost a creation race") from None
    await session.refresh(vpn_user)
    return vpn_user
```

`credit=data_cap_mb` on `IBSngClient.create_user` is the still-open
"credit unit" risk from the parent spec (§5, §14) — the trial being free
makes it a safe first real-world test: if IBSng's credit semantics don't
match `data_cap_mb` 1:1, a mis-sized trial costs nothing, whereas a
mis-sized paid plan would. Whatever's learned here gets documented in
`ibsng/client.py`'s docstring before Buy/Renew ships.

## 5. Eligibility — lifetime, DB-enforced

Homeland's rule ("each telegram user can get just one trial account at
all") is simpler than AloBot's current calendar-month rule, and matches
what AloBot *used* to enforce with a real constraint before their rule
changed to monthly (see `26771c9cb9c9_drop_trial_once_index.py` in
AloBot's history) and they were forced onto an app-only check because a
lifetime unique index can't express "resets every month." Since
Homeland's rule genuinely is lifetime, use the strong version:

```python
# migration: partial unique index, not just an app-level query
op.create_index(
    "ix_vpn_users_trial_once", "vpn_users", ["telegram_id"],
    unique=True, postgresql_where=sa.text("is_trial = true"),
)
```

```python
async def has_used_trial(session: AsyncSession, telegram_id: int) -> bool:
    result = await session.execute(
        select(VPNUser.id).where(VPNUser.telegram_id == telegram_id, VPNUser.is_trial.is_(True)).limit(1)
    )
    return result.scalar_one_or_none() is not None
```

The handler checks `has_used_trial` up front (fast path, good UX — most
repeat taps get an instant answer without attempting IBSng creation).
The index is the actual guarantee (race-safe if two requests from the
same user land concurrently) — `create_vpn_user`'s existing
`IntegrityError` catch already handles that race identically to a
username collision, no new error-handling path needed.

## 6. Trial flow

No FSM states needed — unlike AloBot's multi-step category/location
picker, Homeland's trial is short enough (confirm → protocol → maybe
platform) to run as plain callback-driven screens, consistent with how
`app/bot/handlers/users.py` already works. State that must survive
across taps (which protocol was picked, before asking platform) rides
in the callback_data itself rather than Redis-backed FSM state, since
it's one value threaded through 2-3 screens, not a form being filled in.

**Screens:**

1. **Entry** (`menu:trial` callback, replacing the current placeholder):
   `has_used_trial` check.
   - Already used → "🎁 You've already used your free trial." + Back to Menu.
   - Eligible → "🎁 Free Trial — 24 hours, 1GB of data. Start your trial?"
     + Confirm / Back to Menu.
2. **Confirm** (`trial:confirm`): looks up the Trial plan (`catalog.list_plans(category="trial")[0]`),
   generates credentials (retry up to 3x on `VPNUsernameTakenError`/
   `IBSngUserExistsError`), calls `create_vpn_user(..., is_trial=True)`.
   - Success → proceed to protocol picker (step 3).
   - `create_vpn_user` raises `VPNUsernameTakenError` on the 3rd retry,
     or the partial-unique-index race → "🎁 You've already used your free
     trial." (same message as step 1 — from the user's perspective a
     lost race and an already-used trial look identical).
   - `IBSngError` (real IBSng failure) → "⚠️ Couldn't create your trial
     right now. Please try again shortly." + Back to Menu.
3. **Protocol picker**: "Which protocol do you want to use?" — L2TP / OpenVPN
   buttons + Back.
   - OpenVPN picked → skip straight to delivery (§7) with `platform_id=None`
     (the one shared guide/profile don't need a platform).
   - L2TP picked → **platform picker**: "Which device?" — iOS / Android /
     Windows / macOS + Back.
     - Android picked → Android+L2TP guard (§7) fires, delivery does NOT
       proceed; user sees the compatibility message instead.
     - Any other platform → proceed to delivery (§7).
4. **Delivery** (§7) runs, then the handler itself sends the final
   credentials message (username, password, "valid 24h from first
   connection") once delivery reports success — looked up fresh via the
   just-created `VPNUser` row + `IBSngClient.get_user_password`, not
   carried from the confirm step, since this flow deliberately has no
   FSM state threading a password across callbacks. Every screen
   above has a Back button per the standing UX rule; the protocol/platform
   pickers' Back returns to the previous picker, not all the way to the
   main menu (matches AloBot's back-one-step convention within a flow).

## 7. Delivery service

```python
# app/services/tutorial_delivery.py (new file)
async def deliver_setup(
    bot: Bot, telegram_id: int, session: AsyncSession, *,
    protocol_id: int, platform_id: int | None,
) -> tuple[bool, int | None]:
    """Shared by trial now, Buy/Renew later - ported from AloBot's
    deliver_platform_protocol_setup, minus the category/location
    dimension Homeland doesn't have. Returns (delivered, guide_message_id)
    - delivered=False means the caller must NOT send credentials
    (currently only the Android+L2TP compatibility gate)."""
```

Sequence (unchanged from AloBot, category/location args dropped):

1. **Compatibility gate**: if platform label is "Android" and protocol
   label is "L2TP" → edit the picker message to a fixed warning ("L2TP
   isn't supported on Android 12+ — please use OpenVPN instead, or
   contact support.") and return `(False, None)`.
2. Look up the `TutorialGuide` for `(platform_id, protocol_id)`
   (`platform_id` is `None` for OpenVPN).
3. If protocol is OpenVPN, look up the matching `OpenVpnProfile`
   (platform-specific row wins over the generic `platform_id=None` row,
   same precedence as AloBot's `find_matching_profile`).
4. Send the OpenVPN profile first, if resolved (file replay via the
   matching `bot.send_*` for `file_type`, or plain text if only `text`
   was set).
5. Send the tutorial guide (file replay, or `body_html` text) — or, if
   none exists yet, "📚 This guide isn't ready yet — please contact
   support." (graceful fallback, not a crash; content gets added via
   the admin flow in §8).
6. Send the app download link if one is configured
   (`AppConfig` key `download_link:{protocol_label_lower}:{platform_label_lower}`,
   e.g. `download_link:openvpn:ios`) — skip silently if not set.
7. Return `(True, guide_message_id)`. `deliver_setup` does NOT send the
   credentials message itself — that's the caller's job (the trial
   handler, §6), since only the caller has the freshly-generated
   username/password in scope, and not every future caller (Buy/Renew)
   will want the same trial-specific closing text. `delivered=False`
   means the caller must skip its own credentials message too (the
   Android+L2TP gate is the only case today).

## 8. Minimal admin content management

Without *some* way to add real guides/profiles, this feature stays
permanently empty. Scoped tightly — just enough to make delivery
functional, not the full admin panel (broadcast/discounts/reports stay
in their own later sub-project per the parent spec §7):

- **Entry point (as shipped): a standalone `/admintutorials` command**,
  not an `/admin` → "📚 Tutorials & Profiles" button. This spec was
  written assuming a general `/admin` root menu; the implementation plan
  built the standalone command instead, because the general Admin Panel
  (broadcast/discounts/reports, §9) is its own later sub-project and
  there is no `/admin` root to hang a button off yet. The command is
  gated inside the handler by `has_level(..., "support")` — a non-admin
  who issues it gets no response at all. It is advertised in
  `bot.set_my_commands()` (app/main.py) so admins can discover it;
  Telegram's per-scope command lists can't express "only the admins in
  our database", so it's listed for everyone and gated at the handler,
  the same trade-off the main menu's admin button already makes. When
  the real `/admin` panel lands, it should grow a "📚 Tutorials &
  Profiles" button that jumps into this same flow.
- **Add/edit a guide**: pick protocol → pick platform (or "Generic (any
  platform)" for OpenVPN) → send a photo/document/video → saved as that
  `(platform_id, protocol_id)`'s `TutorialGuide`, upserting if one
  already exists. A guide is media-only from this flow, so a plain-text
  message is rejected rather than saved: writing `media_file_id=None`
  would silently blank out an already-configured guide.
- **Add/edit an OpenVPN profile**: pick protocol → pick platform or
  "generic" (`platform_id=NULL`) → send a file or type config text →
  saved. Text-only is legitimate here (`OpenVpnProfile.text`); a message
  with neither a file nor text is rejected.
- **Set a download link**: pick protocol + platform (or "generic") →
  type a URL → written to the matching `AppConfig` key
  (`download_link:{protocol}:{platform}`, with `any` as the platform
  segment for a generic link — `deliver_setup` falls back to that key
  when no platform-specific link is configured).
- Every screen in the flow carries a "⬅️ Back" button (the root screen's
  returns to the main menu; each later screen's steps back one screen),
  per the standing UX convention in `CLAUDE.md`.
- Platforms/protocols themselves are seeded once via migration (the 4
  platforms, 2 protocols already known from parent spec §9) — no
  admin CRUD for those yet, matching how `Plan` rows are seed-only today.

This is a short FSM-based flow (admin picks options, then the next
message they send — photo/document/text — is captured), analogous to
AloBot's `tutorial_admin.py`/`openvpn_profile_admin.py` states, simplified
by dropping their category/location dimension.

## 9. Out of scope for this spec

- Buy/Renew flows themselves (separate, later sub-project) — this spec
  only builds the delivery mechanism they'll reuse.
- The rest of the admin panel (broadcast, discount codes, sales
  reports, basic user/service ops) — parent spec §7, its own sub-project.
- Actually resolving the IBSng credit-unit question with certainty —
  this spec's trial creation is the first live data point, not a
  guaranteed resolution; `ibsng/client.py`'s docstring gets updated with
  whatever is observed, same as every other confirmed-against-the-real-server
  quirk already documented there.
- Multiple trial accounts, gifting, or referral-based extra trials —
  strictly one per Telegram user, lifetime, no exceptions mechanism.

## 10. Open questions resolved during design

- Username prefix: `hl.` (Homeland), parallel to AloBot's `alo.` — flag
  if a different prefix is preferred, otherwise this ships as the default.
