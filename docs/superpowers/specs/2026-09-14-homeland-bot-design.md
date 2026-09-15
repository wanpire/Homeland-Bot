# Homeland Bot — Design Spec

Date: 2026-09-14
Status: proposed
Amended: 2026-09-15 — catalog corrected to the real 7 IBSng groups (was a
4-plan placeholder), Scroll/Stream categories added, trial flow restored
as its own future plan, group-namespace isolation and dedicated-server
deployment requirements added. See §3, §4, §11, §14.

## 1. Product summary

Homeland is a Telegram bot that sells "reverse VPN" service — Iran-based IP
addresses — in USD to Iranian customers living outside Iran. It is a
separate project, bootstrapped from the existing AloBot codebase
(`/Users/peyman/telegram-bot`, Python 3.12 / aiogram 3.x / PostgreSQL +
SQLAlchemy 2.0 + Alembic / Redis), which sells the opposite direction of
VPN in Toman to customers inside Iran. Homeland reuses AloBot's proven
architecture and its IBSng integration pattern, but trims its feature set
to a much smaller, English-only, USD product and adds data-quota tracking,
which AloBot has never needed.

Backend accounting/provisioning is IBSng, the same software AloBot
integrates with, running on the same shared instance (confirmed: same
IBSng instance/URL, separate ISP name, credentials, and groups for
Homeland — see §14 for the group-namespace isolation requirement this
implies). Homeland runs on its own dedicated server, separate from
AloBot's host, and reaches the shared IBSng instance over the network
(see §11).

## 2. Scope

### 2.1 Kept from AloBot (ported/adapted)

- aiogram 3.x router-per-domain structure, registered in `app/main.py`.
- Stack: PostgreSQL + SQLAlchemy 2.0 + Alembic, Redis for FSM state and
  background tasks, pydantic-settings, Docker Compose.
- `app/services/ibsng/client.py` — the XML-RPC `IBSngClient`, including
  every confirmed-against-a-real-server quirk documented in its module
  docstring (owner_name requirement, flat updateUserAttrs shape,
  getUserInfo's attrs-vs-basic_info split, etc.). Extended with a new
  `get_user_data_usage()` method (see §5).
- Auth / blocked-user / private-chat-only / user-tracking middlewares,
  unchanged.
- Discount codes (`discount_code.py`, `discount_code_usage.py`,
  `discounts.py`), broadcast, sales reports — ported and adapted (see
  §7).
- Expiry reminders (`services/reminders.py`) — ported, plus a new
  low-quota reminder (see §8).
- The standing UX rule: every interactive flow/menu includes a "Back"
  (and "Back to Menu" where relevant) button by default.
- `AppConfig` key/value store for admin-editable runtime settings
  (support text, ToS/Privacy content, reminder on/off).

### 2.2 Dropped entirely

- AloBot's own trial mechanics (`states/trial.py`, `services/*trial*`,
  `set_trial` admin flow, calendar-month eligibility) — **superseded,
  see §2.3**: Homeland restores a trial button, but as its own
  from-scratch feature (one-per-user lifetime limit, not AloBot's
  per-calendar-month rule), built in a future plan, not ported.
- Resellers (`db/models/reseller.py`, `services/resellers.py`,
  `states/reseller_buy.py`, `states/add_reseller.py`) — not in scope
  yet; may return in a later phase but nothing in this design should
  make adding it back harder.
- `dns_switcher.py` and `dns_admin.py` — AloBot-specific Cloudflare
  datacenter switching for its own outbound VPN targets; irrelevant to
  Homeland.
- AloBot's 4-way category matrix (normal/prime/fixed/junior), fixed
  *locations* (`service_location.py`), and the *user_count* dimension.
  **Partially superseded, see §4**: Homeland does have a category
  concept (Scroll/Stream, plus trial), but it's a single flat field on
  `Plan`, not a matrix dimension crossed with location/user_count —
  there is still no location or user_count axis.
- Card-to-card manual payment, the "✅ تایید" admin-approval button, and
  the auto-approve background review loop (`services/auto_approve.py`)
  — Homeland's only payment methods are Stripe and crypto, both
  webhook-confirmed, no manual admin approval step.
- Persian-digit / RTL / bidi text helpers (`to_persian_digits`,
  `isolate_ltr`) and Toman price formatting — Homeland is English/USD
  only.
- `openvpn_profiles.py`'s category/location-bound `.ovpn` profile
  matrix — replaced by a single OpenVPN Connect tutorial guide (§6).

### 2.3 New for Homeland

- Data-quota tracking end to end (IBSng read, `My Services` display,
  low-quota reminder).
- `PaymentProvider` abstraction with Stripe and crypto implementations
  (both stubbed, no live keys). A flat 10%-off-for-crypto discount
  applies to every plan's listed USD price — computed dynamically at
  checkout by whichever provider is selected (not a stored per-plan
  field), so it can't drift from the base price. Built when the payment
  plan is built, not part of the catalog itself.
- USD price formatting.
- ToS/Privacy delivery (static route + in-bot section).
- A from-scratch free trial: one 24-hour, 1GB trial account per
  Telegram user, lifetime (not AloBot's calendar-month rule), bound to
  the reserved `Trial-Iran` IBSng group (§4, §14). Own main-menu button
  ("🎁 Free Trial"), own future plan — not part of this catalog
  correction, which only adds the button as a placeholder (§3).

## 3. Main user menu

Replaces AloBot's menu entirely:

- 🔑 Buy Subscription
- ♻️ Renew Service
- 🛍 My Services (shows remaining data quota, not just expiry)
- 🎁 Free Trial (one per Telegram user, lifetime — see §2.3, §4, §14;
  button exists from this correction onward, but is a placeholder until
  the trial plan builds the real flow, same as every other button below
  until its own plan lands)
- 📚 Tutorial & Support (includes Terms & Privacy)

Every screen reachable from here keeps a Back / Back to Menu button,
per the standing UX rule.

## 4. Catalog: flat plans with a category field, not a matrix

AloBot's `Service` model is a 4-dimensional matrix (category × location ×
duration × user_count) bound to an IBSng `Group`. Homeland is simpler —
one category field, no location or user_count axis — but does need a
category, because the real product has two paid tiers users choose
between (Scroll: lighter/cheaper plans; Stream: heavier/pricier plans),
plus a third pseudo-category for the free trial:

```python
class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int]
    name: Mapped[str]              # "2 Weeks", "1 Month", "2 Months", "3 Months", "Trial"
    category: Mapped[str]          # "scroll" | "stream" | "trial"
    duration_days: Mapped[int]     # 1 (trial), 14, 30, 60, 90
    data_cap_mb: Mapped[int]       # 1024 (trial), 5120, 10240, 20480, 30720, 61440, 102400
    price_usd: Mapped[Decimal]     # 0 (trial), 3.00 .. 29.00
    group_name: Mapped[str]        # bound IBSng group - must be in the Iran namespace, see §14
    is_active: Mapped[bool]
    sort_order: Mapped[int]
```

Seeded once via an Alembic data migration with the 7 plans below (the
real IBSng groups on the shared instance, confirmed 2026-09-15 — this
replaces an earlier 4-plan/4-placeholder-group table from initial
development, corrected before any real deployment). Admin can edit
price / active state / group binding, but cannot create new plans
through the bot — there is no plan editor beyond that, just a plan
list, same as before.

| Name      | Category | Duration | Data cap | Price | IBSng group          |
|-----------|----------|----------|----------|-------|-----------------------|
| Trial     | trial    | 1 day    | 1 GB     | $0    | `Trial-Iran`           |
| 2 Weeks   | scroll   | 14 days  | 5 GB     | $3    | `2W-1U-Iran-5G`        |
| 1 Month   | scroll   | 30 days  | 10 GB    | $5    | `1M-1U-Iran-10G`       |
| 2 Months  | scroll   | 60 days  | 20 GB    | $9    | `2M-1U-Iran-20G`       |
| 1 Month   | stream   | 30 days  | 30 GB    | $12   | `1M-1U-Iran-30G`       |
| 2 Months  | stream   | 60 days  | 60 GB    | $20   | `2M-1U-Iran-60G`       |
| 3 Months  | stream   | 90 days  | 100 GB   | $29   | `3M-1U-Iran-100G`      |

Two plans share the name "1 Month" (10GB/scroll vs. 30GB/stream) and
two share "2 Months" (20GB/scroll vs. 60GB/stream) — they're
distinguished by category (shown as a separate screen/section in Buy
Subscription, not by name alone) and by their data cap in the plan's
own display line. Not a naming collision to fix; category is what
disambiguates them.

`app/services/catalog.py` gains `list_plans(session, *, category=None,
active_only=True)` (category filter added; everything else unchanged
from the original design) plus a `CATEGORIES = ("scroll", "stream",
"trial")` constant. No location/slot-matrix logic, no
`format_plan_title`/Persian-digit helpers. Price formatting stays the
plain `f"${price:.2f}"` helper.

## 5. Data quota — the new integration surface

AloBot's plans are confirmed unlimited-volume (its own code comment:
"every plan is unlimited-volume, so quota is a flat, unconditional
line"). Homeland's core "My Services" requirement — remaining data
quota, not just expiry — needs real usage data from IBSng, which
requires the IBSng groups behind Homeland's 4 plans to be configured for
**volume/traffic-based accounting** (credit = data cap), not AloBot's
time-based groups.

**Deployment prerequisite (blocks this feature, not the rest of the
build):** the 4 IBSng groups for Homeland's plans must exist and be
configured for volume-based credit before quota display can show real
numbers. They are not set up yet as of this spec. Build proceeds against
this design; the exact credit unit (bytes / KB / MB — undocumented, like
every other IBSng behavior recorded in `ibsng/client.py`'s module
docstring) will be confirmed against the real server during integration
testing, and `ibsng/client.py`'s docstring will be extended with
whatever is confirmed, matching its existing documentation style.

Design:

- `IBSngClient.get_user_data_usage(user_id)` reads consumed/total
  traffic. **Not `user_balance.getUserBalanceInfoByUserID`** — AloBot's
  own codebase confirms this handler fails on the real server ("Handler
  --user_balance-- not found", confirmed live twice; it's dead code in
  AloBot, never called, kept only because `scripts/ibsng_probe.py` was
  built to test exactly this and found it broken). Since Homeland shares
  that IBSng server, the same failure is expected. The implementation
  task for this method must first probe the real server (same
  probe-script pattern) for a working alternative — other `user_balance.*`
  methods, fields already present on `user.getUserInfo`'s `attrs`
  (e.g. a credit/traffic field alongside `nearest_exp_date`), or an
  `accounting.*` handler — and implement against whichever actually
  works, documenting the confirmed shape in `ibsng/client.py`'s
  docstring exactly like every other quirk already recorded there.
- `create_user` assigns IBSng credit equal to the plan's `data_cap_mb`
  at purchase/renewal time, instead of AloBot's hardcoded
  `DEFAULT_CREATE_CREDIT = 10`.
- `VPNUser` gains `data_cap_mb: Mapped[int]` (snapshot of the plan's cap
  at purchase time, so a later plan price/cap edit never retroactively
  changes an existing subscription — mirrors how `Payment.amount`
  already snapshots price) and `low_quota_reminder_sent_at: Mapped[dt.datetime | None]`
  alongside the existing `expiry_reminder_sent_at`.
- `My Services` and the low-quota reminder both read usage live from
  IBSng on each call, exactly like `expires_at` is read live today via
  `get_user_expiry` — no local usage caching.

## 6. Payment abstraction

```python
# app/services/payments/base.py
class PaymentProvider(ABC):
    @abstractmethod
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> str:
        """Returns a URL (or client secret) to hand the buyer."""

    @abstractmethod
    async def verify_webhook(self, request: web.Request) -> WebhookEvent | None:
        """Verifies signature, parses the callback. None if invalid/irrelevant."""

    @abstractmethod
    async def on_payment_confirmed(self, event: WebhookEvent) -> None:
        """Creates/renews the VPN user and marks the Payment approved -
        the same logic AloBot's approve_payment_by_id and webhook handler
        both call, unified into one path since Homeland has no manual
        admin-approval branch."""
```

- `app/services/payments/stripe_provider.py` and `crypto_provider.py`
  implement it. Both read placeholder settings that don't exist yet —
  `stripe_api_key: str = ""`, `stripe_webhook_secret: str = ""`,
  `crypto_gateway_api_key: str = ""`, `crypto_gateway_ipn_secret: str = ""`
  — same "optional, blank until provisioned" pattern AloBot already
  uses for `dns_switcher_base_url`/`nowpayments_api_key`. Calling
  `create_invoice` with a blank key raises a clear
  `PaymentProviderNotConfiguredError` rather than a confusing API
  failure, so the bot can run today with payment methods visibly
  "coming soon" until real keys are added later.
- `app/webhook.py` generalizes AloBot's single-purpose NowPayments
  route into one route per registered provider
  (`/webhooks/stripe`, `/webhooks/crypto`), each provider verifying its
  own signature before touching the DB — same shape as today's
  `_handle_nowpayments_ipn`.
- `crypto_provider.py` follows the same hosted-invoice pattern as
  AloBot's `nowpayments.py` (their existing crypto gateway), since
  that's the closest confirmed reference implementation; the concrete
  crypto gateway can be swapped later without touching the interface.
- No card-to-card path. `Payment.method` becomes `"stripe" | "crypto"`.

## 7. Admin panel

Included:
- **Broadcast** — ported as-is.
- **Discount codes** — ported, scoped to `plan_id: int | None` (null =
  all plans) instead of AloBot's category scope, since Homeland has no
  categories. Percent, usage limit, public/private — unchanged.
- **Sales reports** — ported, grouped by plan instead of category; no
  reseller-commission section.
- **Basic service/user ops** — lookup a user/service, lock, manual
  renew/revoke (admin escape hatch for support cases).
- **Content admin** — editable support text and ToS/Privacy content via
  `AppConfig`, reminder on/off toggle.

Excluded (per your answer): DNS admin, resellers (not yet), the
category/location/group-matrix admin screens (no matrix exists).

## 8. Reminders

`services/reminders.py` ported with two checks per cycle instead of one:
- Expiry reminder (unchanged: 24h-before window, `expiry_reminder_sent_at`
  gates it, cleared on renewal).
- **New** low-quota reminder: fires once per cycle when
  `used_mb / data_cap_mb` crosses a threshold (proposed 90%, admin-
  configurable via `AppConfig` like `reminder_enabled` already is),
  gated by the new `low_quota_reminder_sent_at`, cleared on renewal
  alongside the expiry one. Both reminders push the user toward "Renew
  Service".

## 9. Protocols & tutorials

Only L2TP and OpenVPN are offered — no protocol restriction per plan,
every plan can use either.

`TutorialPlatform` / `TutorialProtocol` / `TutorialGuide` ported as-is
structurally, but with the category/location dimensions dropped (neither
exists in Homeland) — a guide is keyed on `(platform_id, protocol_id)`
only. Seeded content:
- L2TP × {iOS, Android, Windows, macOS} — 4 separate guides.
- OpenVPN × OpenVPN Connect — 1 guide (covers the app across platforms;
  the schema still allows splitting into per-platform OpenVPN guides
  later without a model change, same as AloBot's guide system already
  supports for any platform/protocol pair).

Each purchased service's post-purchase flow shows protocol-specific
setup instructions (mirrors AloBot's `start_post_purchase_setup`).

## 10. Terms of Service / Privacy Policy

Needed for Stripe merchant onboarding, which expects a real URL, not a
Telegram deep link. Delivered two ways from one `AppConfig`-stored
source:
- A static HTML route on the existing aiohttp webhook app —
  `GET /legal/terms`, `GET /legal/privacy` — simple server-rendered
  page, no separate static site.
- A "Terms & Privacy" entry under Tutorial & Support showing the same
  text in-bot.

## 11. Infrastructure isolation

Own Docker Compose project (own project name, own network — no
`dns-switcher-net` dependency), own `Dockerfile`/`requirements.txt`, own
Postgres database and role (`homeland`/`homeland`, separate from
AloBot's `vpnbot`), own Redis **container** (full isolation rather than
sharing AloBot's Redis with a different DB index — simpler to reason
about and avoids any risk of FSM key collisions between the two bots),
own bot token. `IBSNG_BASE_URL` points at the same IBSng server AloBot
uses (confirmed), with Homeland's own `IBSNG_ISP_NAME`, credentials, and
groups — the existing config pattern (`app/config.py`'s `Settings`)
already supports this with zero code changes, just a separate `.env`.

**Dedicated server (added 2026-09-15):** Homeland runs on its own
server, separate from AloBot's host, provisioned specifically to avoid
resource contention with AloBot — it hosts Homeland's own bot/Postgres/
Redis containers, but does NOT run its own IBSng; IBSng stays on the
existing datacenter infrastructure (Active/Passive nodes) and is
reached over the network. Before deploying to this server, confirm:
- The reachable `IBSNG_BASE_URL` (host/port) for the shared instance
  from the new server, and that firewall rules between the two allow
  the XML-RPC traffic (IBSng's API defaults to `127.0.0.1` unless
  `IBS_SERVER_IP` is overridden on the IBSng side — confirm which
  address it's actually listening on).
- This server's Docker Compose project name/network stay distinct from
  AloBot's even though they're now on different hosts (already true per
  the isolation above — no change needed, just re-confirm at deploy
  time so container/volume names never collide if the two hosts are
  ever consolidated or put under shared monitoring later).
- `.env` points at Homeland's own Postgres/Redis on the new server,
  never AloBot's — already guaranteed by the isolation above, re-state
  here since it's the thing to double-check during the actual deploy.

## 12. Repository

Fresh `git init` at `/Users/peyman/Homeland-bot` (this repo) —
independent history, not a clone of `telegram-bot`. Relevant AloBot
files are copied and adapted, not shared via git history or a
subtree/submodule.

## 13. Out of scope for this design (explicitly deferred)

- Real Stripe/crypto API keys and going live with payments — keys are
  provisioned and added separately, per your instruction. Config
  placeholders only.
- Resellers.
- Any admin screen beyond §7.
- CI/CD, GitHub Actions — deploy access and the actual push will follow
  once the initial build is done, per your message.

## 14. Open risks to verify during implementation

- **No confirmed working IBSng call for usage data.**
  `user_balance.getUserBalanceInfoByUserID` — the obvious candidate —
  is confirmed dead on this server (see §5). The quota-reading task
  must probe the real server for a working alternative before the
  feature can be considered done; until then `get_user_data_usage`
  should be built against a fake/mocked handler (mirroring
  `tests/fakes/fake_ibsng_server.py`'s pattern) so the rest of the
  My Services / reminders work isn't blocked on IBSng access.
- **IBSng credit unit for volume accounting** — unconfirmed until tested
  against the real server with real volume-accounted groups (still
  open; group *existence* was confirmed 2026-09-15, see below, but
  their accounting-mode configuration was not part of that check).
- **IBSng group existence — RESOLVED 2026-09-15.** All 7 real Homeland
  groups (§4) confirmed present on the production IBSng server via a
  live, read-only `group.listGroups` probe from the deployed bot
  server (`bot.alonet.co`) against `ibsng.alonet.co`: `2W-1U-Iran-5G`,
  `1M-1U-Iran-10G`, `2M-1U-Iran-20G`, `1M-1U-Iran-30G`,
  `2M-1U-Iran-60G`, `3M-1U-Iran-100G`, `Trial-Iran`. The same probe
  also confirmed the group-namespace isolation filter (below) correctly
  separates all 7 from all 15 of AloBot's real groups on the same
  instance, including `-Junior` tier and `Trial-Junior`/`Trial-Prime`
  groups not previously enumerated anywhere in this spec — the filter
  is pattern-based, not a hardcoded list, so it held up against real
  data it was never specifically tuned against. Whether each group is
  configured for volume-based accounting (the credit-unit risk above)
  was not checked by this probe and remains open.
- **Group-namespace isolation (added 2026-09-15).** Homeland shares one
  IBSng instance with AloBot, a separate, unrelated Telegram bot project
  with its own groups (Normal/Prime/Junior tiers — e.g. `1M-1U`,
  `1M-2U`, `1M-1U-Prime`, plain `Trial`, etc.). Homeland must NEVER
  read, list, assign, sync, or otherwise interact with any AloBot
  group. Every one of Homeland's own groups matches the pattern
  `startswith(("2W-", "1M-", "2M-", "3M-", "Trial-")) and "Iran" in
  name` (confirmed against the 7 names in §4 — none of AloBot's group
  names match this pattern). `app/services/groups.py`'s `sync_groups`
  is the ONLY code path that ever populates the local `groups` table
  from `IBSngClient.list_groups()` (which itself returns every group on
  the shared instance, Homeland's and AloBot's alike) — it MUST filter
  to this allowlist before upserting anything, and any future
  group-listing/selection/admin-panel code that calls
  `IBSngClient.list_groups()` directly (bypassing the local table) must
  apply the same filter before presenting options to anyone. `Trial-Iran`
  matches the allowlist and should sync normally, but no `Plan` should
  ever bind a NON-trial (paid) plan to it — it's reserved for the trial
  flow (§2.3) exclusively, never reused or deleted.
