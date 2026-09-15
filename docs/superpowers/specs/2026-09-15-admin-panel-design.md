# Admin Panel (v1) — Design Spec

Date: 2026-09-15
Status: proposed
Parent spec: `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` (§7 — this
spec implements the admin panel that parent spec deferred, scoped down to
what's actually buildable before Buy/Renew/Payments exist)

## 1. Summary

Ported from AloBot's proven admin panel mechanics (`/Users/peyman/telegram-bot`),
scoped to what's genuinely useful and testable today: Homeland has no
`Payment` model and no Buy/Renew user flow yet, so anything that reports on
or operates through purchases can't be meaningfully built or validated —
those pieces are explicitly deferred, not stubbed.

**Built now:**
1. Admin root menu — tier-gated navigation shell (`adm:*` namespace).
2. Broadcast — compose → confirm → background send to all `bot_users`.
3. Discount codes — model + full CRUD, scoped to `plan_id` (Homeland has
   flat plans, not AloBot's categories). `validate_discount_code`/
   `find_best_auto_discount` built now for the future Buy flow to call.
4. Block/unblock users — by Telegram ID, reusing the bot_users service
   that already exists.
5. Admin renew-by-username — the one genuinely new capability this spec
   adds beyond porting: Homeland currently has **no way to extend a
   service at all**, not even manually. Fills that gap.
6. Support contact config — a single `AppConfig`-backed text setting.

**Explicitly deferred (not stubbed):**
- Sales reports — AloBot's `sales_report()` sums approved `Payment` rows;
  Homeland has no `Payment` model and no purchases beyond free trials.
  Building this now would be dead code with nothing to validate it
  against. Revisit once Buy/Payments exist.
- Discount code *usage logging* (`DiscountCodeUsage`, `increment_discount_usage`,
  `log_discount_usage`) — all FK to `payments.id`, which doesn't exist.
  The `DiscountCode` model, CRUD, and validation land now; usage tracking
  lands with the Buy/payments plan.
- Admin management UI (add/remove other admins) — the bootstrap `ADMIN_IDS`
  env var already covers "full" tier; a management UI is a nice-to-have,
  not a blocker, and adds scope without an urgent need.
- Reseller/channel-membership/card-payment settings — not applicable to
  Homeland's product (parent spec §2.2).

## 2. Auth tiers (already exist, unchanged)

`app/services/admin_users.py`'s `has_level(session, telegram_id, min_level)`
and `LEVELS = ("support", "sales", "full")` already exist from the
bootstrap slice — this spec just uses them. Per AloBot's tier semantics,
adapted:
- **support**: broadcast view-only actions, renew-by-username, block/unblock.
- **sales**: + discount codes.
- **full**: + support-contact config, group sync.

Two new `BaseFilter` classes, ported directly from AloBot's `IsSalesAdmin`/
`IsFullAdmin` (an `IsAdmin`-equivalent isn't needed as a separate filter —
the admin router's own base gate uses `has_level(..., "support")` inline,
matching how `blocked_user.py`'s middleware already does the same check):

```python
class IsSalesAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        async with async_session_maker() as session:
            return await has_level(session, user.id, "sales")

class IsFullAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        async with async_session_maker() as session:
            return await has_level(session, user.id, "full")
```

Router-level gating, ported from AloBot: the `admin` router's base filter
requires "support"; `broadcast`/discount-admin routers require "sales" or
"full" at the router level (matching AloBot's `router.message.filter(...)`
pattern); individual full-admin-only buttons inside a support-reachable
section are hidden (not just filter-gated) from lower tiers, since a
visible-but-nonfunctional button gives zero feedback when its filter
silently doesn't match — the exact reasoning already baked into AloBot's
`admin_root_menu`.

## 3. Navigation shell

Callback-data namespace: `adm:*`, colon-separated path segments, ported
directly from AloBot's convention (`adm:root`, `adm:broadcast`,
`adm:discounts:new`, etc.) — this ALSO resolves the placeholder `adm:root`
callback that's existed since the bootstrap plan's Task 8 (currently
answers "coming soon"; this spec gives it a real destination).

Root menu (adapted from `admin_root_menu`, only the sections this spec
builds):

```python
def admin_root_menu(*, is_sales_admin: bool, is_full_admin: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Broadcast", callback_data="adm:broadcast")
    builder.button(text="👤 Users", callback_data="adm:users")
    builder.button(text="📚 Tutorials & Profiles", callback_data="adm:tutorials")
    if is_sales_admin:
        builder.button(text="🏷 Discount Codes", callback_data="adm:discounts")
    if is_full_admin:
        builder.button(text="⚙️ Settings", callback_data="adm:settings")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    ...
```

`adm:tutorials`'s handler is a thin adapter: the existing `/admintutorials`
command handler (`app/bot/handlers/tutorial_admin.py`'s `admin_root_cmd`)
already does exactly two things after its permission check —
`message.answer(text, reply_markup=tutorial_admin_root_keyboard())`. The
adapter callback does the identical check-then-render, just via
`callback.message.edit_text(...)` instead of `message.answer(...)`
(matching every other `adm:*` section handler's edit-in-place convention)
— no change to `tutorial_admin.py`'s own state machine or any other
handler in that file. The standalone `/admintutorials` command keeps
working unchanged for anyone who types it directly.

`adm:users` sub-menu: "♻️ Renew a Service" (renew-by-username, §6) and
"🚫 Blocked Users" (§5). `adm:settings` sub-menu (full-admin only):
"☎️ Support Contact" (§7) and "🔄 Sync IBSng Groups" (§8).

Same navigation conventions as AloBot throughout, ported directly: every
leaf screen has a "🔙 Back" (one step) and/or "🔙 Back to Admin Panel"
(jump to root); destructive actions (delete a discount code) always go
through a two-tap confirm (`confirm_delete_keyboard` equivalent); FSM
text-input steps use a "❌ Cancel" (first step) or "🔙 Back + ❌ Cancel"
(later steps) keyboard pair.

## 4. Broadcast

Ported from AloBot's `broadcast.py`/`states/broadcast.py` essentially
unchanged — the mechanics have nothing category/plan/payment-specific
about them:

```python
class BroadcastStates(StatesGroup):
    content = State()
    confirm = State()
```

Flow: `adm:broadcast` → prompt for text/photo/document → capture into
`{"kind": "text"|"photo"|"document", ...}` → confirm screen showing
recipient count (`len(await list_bot_user_ids(session))`, already exists)
→ on confirm, `asyncio.create_task` a background sender loop (0.05s
delay between sends, ~20/sec, under Telegram's rate limit) that swallows
per-recipient `TelegramAPIError` (blocked/deleted accounts are normal at
scale, never abort the run) and DMs the admin a "✅ Done — sent: N,
failed: N" summary when finished. Gated `IsFullAdmin` at the router level,
matching AloBot (broadcast reaches every user — highest-consequence admin
action, reserved for full admins).

## 5. Block/unblock users

Already has everything it needs from the bootstrap slice —
`app.services.bot_users.block_user(session, telegram_id, blocked=True)`
already toggles both directions (simpler than AloBot's separate
`block_user`/`unblock_user` pair). This spec adds only the UI:

```python
class BlockUserStates(StatesGroup):
    telegram_id = State()
```

`adm:users:blocked` → paginated list (8/page, matching AloBot's
`_BLOCKED_PAGE_SIZE`) of currently-blocked `BotUser` rows, each row a
button that unblocks on tap (no separate detail screen needed — nothing
else to show), plus a "🚫 Block a User" button starting the reverse flow
(type a numeric Telegram ID → validate → `block_user(..., blocked=True)`).
Gated `has_level(..., "support")` (matches AloBot).

## 6. Admin renew-by-username

The one new capability. Homeland's `VPNUser`/`Plan`/`IBSngClient`
foundation has everything to create an account (`create_vpn_user`) and
read one (`get_user_info`/`get_user_expiry`), but nothing to *extend* one
— no Renew flow exists yet, and won't until its own later plan. This
gives support staff a manual override in the meantime, ported from
AloBot's `adm:users:renew` tool (typed username, no search/autocomplete
— matches AloBot exactly, which has no generic user-search screen either).

**New `IBSngClient` method** (missing from the bootstrap port — AloBot's
own docstring flagged it "not yet verified against Free 1.24, fine to
leave as best-effort," which is why it wasn't ported initially):

```python
async def renew_user(self, *, username: str) -> None:
    """Mirrors IBSng's admin-panel 'reset first login' action: clears
    the first_login attribute so validity restarts from the account's
    next connection. Idempotent - deleting an already-unset attribute
    is a no-op, safe to retry."""
    user_id = await self._require_user_id(username)
    await self._call("user.updateUserAttrs", user_id=user_id, attrs={}, to_del_attrs=["first_login"])
```

**New `vpn_users.py` function**, combining renew + optional plan change
in one action (matching AloBot's `renew_and_change_group` — an admin
always re-picks a plan, even if it's the same one, since one action does
both):

```python
async def renew_and_change_group(
    session: AsyncSession, client: IBSngClient, *, username: str, new_group_name: str,
    new_plan_id: int | None, new_data_cap_mb: int,
) -> None:
    """Renews (resets validity) AND moves to a (possibly different)
    group/plan in one IBSng-side action. Updates the locally-tracked
    VPNUser row if this username is tracked (was created through the
    bot) - otherwise this is IBSng-only, no local row to update, and
    the admin's result screen says so."""
    await client.renew_user(username=username)
    await client.change_user_group(username=username, group_name=new_group_name)
    vpn_user = (await session.execute(
        select(VPNUser).where(VPNUser.ibsng_username == username)
    )).scalar_one_or_none()
    if vpn_user is not None:
        vpn_user.ibsng_group = new_group_name
        vpn_user.plan_id = new_plan_id
        vpn_user.data_cap_mb = new_data_cap_mb
        vpn_user.expiry_reminder_sent_at = None
        vpn_user.low_quota_reminder_sent_at = None
        await session.commit()
```

Flow: `adm:users:renew` → prompt for IBSng username → prompt to pick a
plan from `catalog.list_plans()` (reuses the existing catalog, no
category/location picker needed — Homeland's plans are already flat) →
execute → result screen. Errors handled distinctly, matching AloBot:
`IBSngUserNotFoundError` → "user not found"; `IBSngError` → the raw
message; success → "✅ Renewed and moved to {plan.name}", plus, if a
local `VPNUser` row existed, a DM to that Telegram user letting them know
support renewed their service. Gated `has_level(..., "support")`.

## 7. Discount codes

### Model (adapted from AloBot's `DiscountCode`, `categories` → `plan_ids`)

```python
class DiscountCode(Base):
    __tablename__ = "discount_codes"
    id: Mapped[int]
    code: Mapped[str]                    # String(32), unique, always upper-cased
    percent: Mapped[Decimal]             # Numeric(5, 2)
    usage_limit: Mapped[int | None]      # None = unlimited
    used_count: Mapped[int]              # default 0 - not incremented until Buy exists (see §1)
    plan_ids: Mapped[str | None]         # comma-joined Plan IDs; NULL = applies to every plan
    is_active: Mapped[bool]
    is_public: Mapped[bool]              # public = auto-applied/visible; private = only via typed code
    created_at: Mapped[dt.datetime]
```

### Service (`app/services/discounts.py`, adapted from AloBot's exact logic)

```python
def normalize_discount_code(code: str) -> str: ...  # .strip().upper()
def discount_price(original: Decimal, percent: Decimal) -> Decimal: ...  # unchanged from AloBot

async def create_discount_code(session, *, code, percent, usage_limit, plan_ids, is_public=True) -> DiscountCode: ...
async def update_discount_code(session, discount_code_id, *, percent, usage_limit, plan_ids, is_public) -> DiscountCode | None: ...
    # code text itself never editable after creation, matching AloBot
async def set_discount_active(session, discount_code_id, active) -> DiscountCode | None: ...
async def delete_discount_code(session, discount_code_id) -> bool: ...  # hard delete
async def get_discount_code(session, discount_code_id) -> DiscountCode | None: ...
async def get_discount_code_by_name(session, code) -> DiscountCode | None: ...
async def list_discount_codes(session) -> list[DiscountCode]: ...

def _is_within_usage_limit(discount: DiscountCode) -> bool: ...  # unchanged
def _applies_to_plan(discount: DiscountCode, plan_id: int) -> bool:
    return discount.plan_ids is None or str(plan_id) in discount.plan_ids.split(",")

async def validate_discount_code(session, *, code: str, plan_id: int) -> DiscountCode:
    # raises DiscountCodeInvalidError at each failure point, same shape as AloBot:
    # not found / inactive / exhausted / not scoped to this plan
    ...

async def find_best_auto_discount(session, plan_id: int) -> DiscountCode | None:
    # highest-percent active, non-exhausted, PUBLIC code scoped to plan_id.
    # Built now so Buy (later) can call it; unused until then.
    ...
```

`DiscountCodeUsage`, `increment_discount_usage`, `log_discount_usage`:
**not built in this spec** — see §1. `used_count` stays at its default
`0` until the Buy/payments plan wires up the increment call.

### Admin CRUD flow (adapted from AloBot's `discounts.py`/`discount_admin.py`)

```python
class DiscountCodeStates(StatesGroup):
    name = State()
    percent = State()
    usage_limit = State()
    plans = State()
    visibility = State()
```

Wizard order, ported from AloBot exactly: `adm:discounts:new` → type
code (rejected if duplicate, case-insensitive via `normalize_discount_code`)
→ type percent (validated `0 < percent <= 100`) → pick usage limit (type
a number, or tap "⏭ Unlimited") → multi-select plan picker (toggle-per-tap
over `catalog.list_plans()`, "🔘 Select All" toggles all, must select ≥1)
→ public/private picker → save, show detail view. Editing skips the name
step (immutable) and pre-fills the current values, matching AloBot's
`editing_id`-conditional back-target logic exactly.

Detail view, list view, usage-limit picker, plan multi-select, and
public/private picker keyboards all port directly from AloBot's discount
keyboards with `categories`→`plan_ids`/`plan names` substituted — same
toggle/confirm/back conventions as §3.

## 8. Support contact config + group sync

Two small, independent additions to the "Settings" section, both
full-admin only, both trivial given existing infrastructure:

**Support contact**: single-field `AppConfig` flow, ported directly from
AloBot's `EditSupportStates`/support-username pattern — prompt → validate
non-empty → `set_config(session, "support_username", value)` → confirm.
(Nothing currently reads this key yet — Tutorial & Support, a later plan,
will. Setting it now means it's already configured when that lands.)

**Sync IBSng groups**: a single button (`adm:settings:syncgroups`) that
calls the already-existing `app.services.groups.sync_groups(session, client)`
and reports how many Homeland-namespaced groups were found/updated. No
new service logic — this is pure UI wrapping an existing, tested function
from the bootstrap slice.

## 9. Out of scope for this spec

- Sales reports, discount-usage logging, admin-management UI, reseller/
  channel/card settings — see §1.
- Any change to the Buy/Renew/My Services/Tutorial & Support user-facing
  flows — this spec only touches the admin side.
- The Trial flow's own admin content tool (`/admintutorials`) — already
  built in the prior plan, untouched here; it will get folded into this
  admin panel's navigation (an `adm:tutorials` button pointing at the
  existing flow) as a small addition, but its own flow logic is unchanged.
