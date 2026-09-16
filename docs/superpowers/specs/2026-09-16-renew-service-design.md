# Renew Service (v1) — Design Spec

Date: 2026-09-16
Status: proposed
Parent spec: `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` (§5 —
this spec implements the user-facing "renew an owned service" screen)

## 1. Summary

Resolves the `menu:renew` placeholder with a flow that mirrors Buy
Subscription almost exactly, with one extra first step: pick which owned,
non-trial service to renew. From there it's the same category → tier →
price-summary-with-auto-discount screens Buy already built, just with the
service id (`vpn_user_id`) threaded through every callback_data, ending in
the same "payment methods coming soon" wall — **no renewal is actually
executed**. `renew_and_change_group` (`app/services/vpn_users.py`, built
during Admin Panel, currently only called from the admin-initiated renew
flow) is exactly what a real-payment confirmation would eventually call,
but this spec does not wire it up — same deliberate deferral as Buy
Subscription, per the standing instruction to postpone the payment
foundation until real Stripe/crypto credentials are provided.

**Why renewal isn't just "pick a new tier for one service" in one step:**
a renewal is really "buy a plan, applied to an existing service" — same
category/tier/discount/price mechanics as a fresh purchase, so the design
reuses Buy's screens rather than inventing a second pricing UI. The only
new concept is the leading service picker.

**Service picker reuses My Services' ownership infrastructure directly:**
`list_vpn_users_for_telegram_id` and `get_owned_vpn_user`
(`app/services/vpn_users.py`, built for My Services) are reused as-is — no
new query needed. Filtered to non-trial services only: a trial has no
paid plan to renew into, and Free Trial already has its own dedicated
flow (`menu:trial`).

**Plan choice is unrestricted ("any plan"):** the tier picker after
category selection shows every active plan in that category, same as
Buy — a user can renew into a smaller, larger, or same-tier plan as their
current one. There's no attempt to default to or highlight "their current
plan" in this version; that's a possible v2 polish, not required now.

## 2. Navigation

Callback-data namespace: `renew:*`, matching the `menu:*`/`buy:*`/
`myservices:*`/`trial:*`/`adm:*` convention. No FSM state anywhere in this
flow — every screen is reachable from a `vpn_user_id`/`category`/`plan_id`
embedded in callback_data, the same stateless pattern Buy Subscription and
My Services already use.

```
menu:renew                                  -> service picker (resolves the existing placeholder)
renew:service:<vpn_user_id>                  -> category picker, for this service
renew:category:<vpn_user_id>:<category>      -> tier picker, for this service+category
renew:plan:<vpn_user_id>:<plan_id>           -> price summary, for this service+plan
renew:confirm:<vpn_user_id>:<plan_id>        -> "payment methods coming soon" wall
```

**Ownership check, every screen keyed by `vpn_user_id`:** re-verified via
`get_owned_vpn_user(session, vpn_user_id, telegram_id)` (§4) on every one
of the four screens above, not just the first — a user could otherwise
craft a `renew:plan:<someone-else's-id>:<plan_id>` callback directly and
skip the picker entirely. `None` (not found OR not owned by this
telegram_id — same message either way, matching My Services' precedent)
shows a "service not found" message with a Back-to-List button, same
pattern as My Services §5.

Every screen has a Back control: service picker → "⬅️ Back to Menu"
(`menu:root`); category picker → "⬅️ Back to Services"
(`menu:renew`, re-renders the service picker); tier picker → "⬅️ Back"
(`renew:service:<vpn_user_id>`, re-shows the category picker for that same
service); price summary → "⬅️ Back"
(`renew:category:<vpn_user_id>:<category>`, re-shows the tier picker).

## 3. Service picker screen

`menu:renew` calls `list_vpn_users_for_telegram_id` (already exists,
`app/services/vpn_users.py:190`), filters out trial rows, and — same as My
Services' list screen — looks up each remaining row's plan (`get_plan`)
for display. Unlike My Services, this screen does **not** need a live
IBSng status lookup: renewability doesn't depend on active/expired/pending,
so no `IBSngClient` round-trip is needed here (a real payment
confirmation, when it exists, is where `renew_and_change_group` would run
and touch IBSng — not this browsing step).

Zero non-trial services → an empty-state message ("♻️ You don't have any
services to renew yet.") with Buy Subscription / Back to Menu buttons.
Otherwise, one button per service:

```python
async def list_renewable_services(session: AsyncSession, telegram_id: int) -> list[tuple[VPNUser, Plan | None]]:
    vpn_users = await list_vpn_users_for_telegram_id(session, telegram_id)
    rows: list[tuple[VPNUser, Plan | None]] = []
    for vpn_user in vpn_users:
        if vpn_user.is_trial:
            continue
        plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
        rows.append((vpn_user, plan))
    return rows
```

This lives in `app/services/vpn_users.py`, next to `list_services_with_status`
(the equivalent My Services helper) — same shape, minus the status lookup,
plus the trial filter.

```python
def renew_service_keyboard(rows: list[tuple[VPNUser, Plan | None]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        builder.button(text=name, callback_data=f"renew:service:{vpn_user.id}")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def renew_empty_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Buy Subscription", callback_data="menu:buy", style="success")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

## 4. Category picker screen

`renew:service:<vpn_user_id>` re-verifies ownership via
`get_owned_vpn_user` (existing, `app/services/vpn_users.py:182`); `None`
shows the not-found message (§2). Otherwise shows the same two buyable
categories Buy's category picker shows (Scroll/Stream — trial is excluded
there too, for the same reason: `_BUY_CATEGORIES` in
`app/bot/handlers/buy.py:21` already computes this), with the service id
threaded through:

```python
def renew_category_keyboard(vpn_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Scroll", callback_data=f"renew:category:{vpn_user_id}:scroll")
    builder.button(text="🌊 Stream", callback_data=f"renew:category:{vpn_user_id}:stream")
    builder.button(text="⬅️ Back to Services", callback_data="menu:renew")
    builder.adjust(2, 1)
    return builder.as_markup()
```

Text: `f"♻️ <b>Renew {name}</b>\n\nPick a category:"` where `name` is the
plan name (or `ibsng_group` fallback) resolved the same way §3 resolves
it, so the user always sees which service they're renewing.

## 5. Tier picker screen

`renew:category:<vpn_user_id>:<category>` re-verifies ownership, then
validates `category` against a `_RENEW_CATEGORIES` tuple local to the
renew handler, computed the same way Buy's own `_BUY_CATEGORIES` is
(`tuple(category for category in CATEGORIES if category != "trial")`,
`app/bot/handlers/buy.py:21`) rather than importing Buy's constant
directly — keeping the two routers independent, matching the existing
convention that each flow router owns its own copies of small constants
like this. An invalid category falls back to re-showing the category
picker, matching `buy_category_cb`'s own handling
(`app/bot/handlers/buy.py:32-38`). Valid category → `list_plans(session,
category=category, active_only=True)` (existing, `app/services/catalog.py:13`),
rendered with the service id threaded through:

```python
def renew_plan_keyboard(plans: list[Plan], vpn_user_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan.name} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb)})",
            callback_data=f"renew:plan:{vpn_user_id}:{plan.id}",
        )
    builder.button(text="⬅️ Back", callback_data=f"renew:service:{vpn_user_id}")
    builder.adjust(1)
    return builder.as_markup()
```

## 6. Price summary screen

`renew:plan:<vpn_user_id>:<plan_id>` re-verifies ownership, then looks up
the plan via `get_plan` and rejects it the same way Buy's `_is_buyable`
does (`plan is not None and plan.category != "trial"`) — a crafted
`renew:plan:<id>:<trial-plan-id>` callback must be rejected for exactly
the same reason Buy's final review flagged it: harmless today, but the
exact hole that becomes free-service abuse once payments exist. An
invalid plan shows the same `_PLAN_GONE_TEXT` pattern Buy uses, with a
Back-to-Services button.

Valid plan → renders the price summary, reusing `find_best_auto_discount`
and `discount_price` (existing, `app/services/discounts.py:129,20`)
identically to Buy's `_price_summary_text`:

```python
async def _renew_summary_text(session: AsyncSession, vpn_user: VPNUser, plan: Plan) -> str:
    current_name = ...  # same plan-name/ibsng_group resolution as §3
    lines = [
        f"♻️ <b>Renew {current_name} → {plan.name} ({plan.category.title()})</b>",
        f"Duration: {plan.duration_days} days",
        f"Data: {format_data_cap(plan.data_cap_mb)}",
    ]
    discount = await find_best_auto_discount(session, plan.id)
    if discount is not None:
        discounted = discount_price(plan.price_usd, discount.percent)
        percent_text = f"{discount.percent.normalize():f}"
        lines.append(
            f"Price: <s>{format_price_usd(plan.price_usd)}</s> "
            f"{format_price_usd(discounted)} (-{percent_text}%)"
        )
    else:
        lines.append(f"Price: {format_price_usd(plan.price_usd)}")
    return "\n".join(lines)
```

```python
def renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Renew", callback_data=f"renew:confirm:{vpn_user_id}:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"renew:category:{vpn_user_id}:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

## 7. Confirm screen — payment coming soon

`renew:confirm:<vpn_user_id>:<plan_id>` re-verifies ownership and
plan-buyability one last time (same checks as §6 — a screen reached only
by tapping "✅ Renew", but still reachable directly via a crafted
callback, so it gets the same validation every other screen in this flow
gets), then shows the same coming-soon wall text Buy uses:

```python
_COMING_SOON_TEXT = (
    "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
    "the moment they're live. No charge has been made and your service has not "
    "been changed."
)
```

with a Back-to-Menu button. **`renew_and_change_group` is never called
from this handler** — it stays exactly as Admin Panel left it, callable
only from the admin-initiated renew flow, until a real payment
confirmation exists to call it here too.

## 8. Main menu wiring

`app/bot/handlers/users.py`'s `_PLACEHOLDER_CALLBACKS` currently contains
`{"menu:renew", "menu:tutorials"}` (`app/bot/handlers/users.py:20-23`).
This spec removes `"menu:renew"` from that set, the same way My Services
removed `"menu:myservices"` from it. A new `renew` router (mirroring
`buy`/`myservices`) is registered in `app/main.py`'s `build_dispatcher`,
inserted between `buy` and `myservices` (alphabetical-ish grouping with
the other purchase-flow routers, before the ownership-browsing
`myservices` router and the catch-all `users` router) — exact insertion
point is an implementation-plan detail, not a design constraint.

## 9. Out of scope for this spec

- Actually executing a renewal (calling `renew_and_change_group`) — blocked
  on real Stripe/crypto payment credentials, per standing instruction.
  When that foundation lands, `renew:confirm:<vpn_user_id>:<plan_id>` is
  the natural call site.
- Typed discount-code entry — matching Buy's own v1 scope-out ("Auto-apply
  public codes only"), same reasoning applies here.
- Defaulting to or highlighting the service's current plan in the tier
  picker — see §1; a possible v2 polish.
- Any change to the Buy, Trial, My Services, or Admin Panel flows.
