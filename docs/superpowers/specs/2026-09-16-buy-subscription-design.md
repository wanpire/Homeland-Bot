# Buy Subscription (v1) — Design Spec

Date: 2026-09-16
Status: proposed
Parent spec: `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` (§6 — this
spec implements the browsing/pricing half of Buy, scoped down to what's
buildable before Stripe/crypto keys exist)

## 1. Summary

Resolves the `menu:buy` placeholder (currently answered "coming soon" by
`app/bot/handlers/users.py`) with a real catalog-browsing flow: pick a
category, pick a tier, see the price (with any active public discount
auto-applied), then hit a payment-coming-soon wall. No `VPNUser` account
is created anywhere in this flow — that only happens once a real payment
confirms, which is out of scope until the user provides Stripe/crypto API
keys (standing instruction from earlier in this project). This flow reuses
`app/services/catalog.py` and `app/services/discounts.py` as-is — both
already exist, and `discounts.py`'s `find_best_auto_discount` was built
during the Admin Panel plan specifically for this flow to call.

**Built now:**
1. Category picker (`menu:buy` → Scroll / Stream, mirroring `Plan.category`).
2. Tier picker within a category (each plan shown as `{name} — {price}`).
3. Price summary screen — plan details, with the best active public
   discount code auto-applied if one exists for that plan.
4. Payment-coming-soon wall on "Buy" tap.

**Explicitly deferred (not stubbed):**
- Actually creating a `VPNUser` / charging anything — no payment provider
  exists yet (`app/config.py`'s `stripe_api_key`/`crypto_gateway_api_key`
  are still blank placeholders). This flow is read-only browsing + pricing.
- Typed discount-code entry (`validate_discount_code`) — only the
  auto-applied public-code path (`find_best_auto_discount`) is wired up
  for v1. The typed-code UI is a natural extension once a real purchase
  exists to apply it to.
- Post-purchase delivery (protocol/platform picker, credential delivery
  via `tutorial_delivery.deliver_setup`) — these only make sense once an
  account actually gets created, i.e. once payment exists. The trial flow
  (`app/bot/handlers/trial.py`) is the reference for how that will look
  when this flow grows a real "confirm and pay" step.

## 2. Navigation

Callback-data namespace: `buy:*`, colon-separated, matching the `menu:*`/
`trial:*`/`adm:*` convention already used throughout the bot.

```
menu:buy                    -> category picker (resolves the existing placeholder)
buy:category:<scroll|stream> -> tier picker for that category
buy:plan:<plan_id>          -> price summary for that plan
buy:confirm:<plan_id>       -> payment-coming-soon screen
```

Every screen has a Back control, matching CLAUDE.md's standing convention:
category picker → "⬅️ Back to Menu" (`menu:root`); tier picker → "⬅️ Back"
(`menu:buy`, redraws the category picker); price summary → "⬅️ Back"
(`buy:category:<category>`, redraws the tier picker for that same
category — the category is re-derived from the plan looked up by
`plan_id`, not carried in FSM state, since this flow has none); the
coming-soon screen → "⬅️ Back to Menu" (`menu:root`).

No FSM state anywhere in this flow — every screen is reachable from a
plain `plan_id`/`category` embedded in callback_data, the same pattern
`trial.py`'s protocol/platform pickers already use for the parts of that
flow that don't need to remember prior input across a text message.

## 3. Category picker

```python
def buy_category_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Scroll", callback_data="buy:category:scroll")
    builder.button(text="🌊 Stream", callback_data="buy:category:stream")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()
```

`menu:buy`'s handler renders this directly — no DB query needed, the two
categories are fixed (`catalog.CATEGORIES` minus `"trial"`, which has no
Buy entry point — trial is reached only via `menu:trial`).

## 4. Tier picker

```python
def buy_plan_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan.name} — {format_price_usd(plan.price_usd)}",
            callback_data=f"buy:plan:{plan.id}",
        )
    builder.button(text="⬅️ Back", callback_data="menu:buy")
    builder.adjust(1)
    return builder.as_markup()
```

`buy:category:<category>` calls `catalog.list_plans(session, category=category, active_only=True)`
(already exists, already ordered by `sort_order`) and renders this
keyboard. Real data today: Scroll → 2 Weeks/$3, 1 Month/$5, 2 Months/$9;
Stream → 1 Month/$12, 2 Months/$20, 3 Months/$29 (migration `0004`,
unchanged by this spec).

## 5. Price summary

```python
async def _price_summary_text(session: AsyncSession, plan: Plan) -> str:
    lines = [
        f"🔑 <b>{plan.name} ({plan.category.title()})</b>",
        f"Duration: {plan.duration_days} days",
        f"Data: {plan.data_cap_mb // 1024} GB" if plan.data_cap_mb % 1024 == 0 else f"Data: {plan.data_cap_mb} MB",
    ]
    discount = await find_best_auto_discount(session, plan.id)
    if discount is not None:
        discounted = discount_price(plan.price_usd, discount.percent)
        lines.append(f"Price: <s>{format_price_usd(plan.price_usd)}</s> {format_price_usd(discounted)} (-{discount.percent}%)")
    else:
        lines.append(f"Price: {format_price_usd(plan.price_usd)}")
    return "\n".join(lines)
```

`plan.name`/`plan.category` are catalog-controlled, not admin- or
user-typed, so no `html.escape()` is required — matching the precedent
set in the Admin Panel's final review, which only flagged interpolated
*typed* text (admin input, external IBSng error strings) as needing it.

`buy:plan:<plan_id>` looks the plan up via `catalog.get_plan(session, plan_id)`
(404-equivalent: if `None` — deleted/deactivated between screens — show a
"plan no longer exists" message with a Back-to-category button, same
defensive pattern as the Admin Panel's renew flow's `_PLAN_GONE_TEXT`).
Renders the summary text above with a keyboard:

```python
def buy_price_summary_keyboard(plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Buy", callback_data=f"buy:confirm:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"buy:category:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

## 6. Payment-coming-soon wall

`buy:confirm:<plan_id>` re-fetches the plan (same not-found handling as
§5) purely to confirm it's still valid, then always shows:

> 🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know
> the moment they're live. No charge has been made and no account was
> created.

with a "⬅️ Back to Menu" button. Nothing is written to the database.

## 7. Out of scope for this spec

- Actual payment processing, account creation, and post-purchase delivery
  — see §1. Revisit once Stripe/crypto keys are provided.
- Typed discount-code entry — see §1.
- Any change to the Free Trial, Admin Panel, or other existing flows.
