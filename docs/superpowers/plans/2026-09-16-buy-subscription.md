# Buy Subscription (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the `menu:buy` placeholder with a real catalog-browsing flow — category → tier → price summary (with auto-applied public discount) → a payment-coming-soon wall. No account is created anywhere in this flow.

**Architecture:** One new router (`app/bot/handlers/buy.py`) + one new keyboard module (`app/bot/keyboards/buy.py`), wired into `app/main.py`'s `build_dispatcher`, exactly like every prior feature router in this codebase. No FSM state — every screen is reachable from a `plan_id`/`category` embedded in callback_data, mirroring the stateless parts of `trial.py`'s protocol/platform pickers.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async (same as the rest of the repo). No new dependencies, no migration.

**Spec:** `docs/superpowers/specs/2026-09-16-buy-subscription-design.md`

## Global Constraints

- Async only — no blocking I/O in handlers or services (CLAUDE.md).
- Type hints on every function signature (CLAUDE.md).
- All user-facing strings in English (CLAUDE.md).
- Keep handlers thin: parse input, call a service, reply (CLAUDE.md).
- Every interactive flow/menu includes a "Back" button by default (CLAUDE.md).
- `app/main.py`'s `build_dispatcher(storage)` is the single source of truth for router wiring.
- Callback-data namespace is `buy:*`, colon-separated path segments, matching the existing `menu:*`/`trial:*`/`adm:*` convention.
- `plan.name`/`plan.category` are catalog-controlled, not admin- or user-typed — no `html.escape()` needed for them (spec §5), unlike admin-typed or external text elsewhere in the bot.
- This flow creates no `VPNUser` row and calls no IBSng method anywhere — it is read-only browsing + pricing until a payment provider exists.

---

## File Structure

New files:
- `app/bot/keyboards/buy.py` — `buy_category_keyboard()`, `buy_plan_keyboard(plans)`, `buy_price_summary_keyboard(plan_id, category)`.
- `app/bot/handlers/buy.py` — `menu:buy` / `buy:category:*` / `buy:plan:*` / `buy:confirm:*` handlers.
- `tests/functional/test_buy_flow.py`

Modified files:
- `app/bot/handlers/users.py` — remove `"menu:buy"` from `_PLACEHOLDER_CALLBACKS` (Task 1).
- `app/main.py` — register `buy.router` (Task 1).
- `tests/functional/test_start_and_menu.py` — drop `"menu:buy"` from the placeholder-callback test (Task 1).

---

### Task 1: Category + tier picker

**Files:**
- Create: `app/bot/keyboards/buy.py`
- Create: `app/bot/handlers/buy.py`
- Modify: `app/bot/handlers/users.py`
- Modify: `app/main.py`
- Modify: `tests/functional/test_start_and_menu.py`
- Test: `tests/functional/test_buy_flow.py`

**Interfaces:**
- Consumes: `catalog.list_plans(session, *, category=None, active_only=True) -> list[Plan]`, `catalog.format_price_usd(price: Decimal) -> str` (both existing, `app/services/catalog.py`).
- Produces: `buy_category_keyboard() -> InlineKeyboardMarkup`, `buy_plan_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup` (`app/bot/keyboards/buy.py`) — Task 2 adds a third keyboard function to this same file, does not modify these two. Router `buy` registered in `app/main.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_buy_flow.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_buy_shows_category_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🌊 Stream" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_category_shows_scroll_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "2 Weeks — $3.00" in buttons
    assert "1 Month — $5.00" in buttons
    assert "2 Months — $9.00" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_category_shows_stream_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:stream"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "1 Month — $12.00" in buttons
    assert "2 Months — $20.00" in buttons
    assert "3 Months — $29.00" in buttons


@pytest.mark.asyncio
async def test_menu_buy_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)
```

Also edit `tests/functional/test_start_and_menu.py`'s `test_placeholder_callbacks_answer_coming_soon`: remove `"menu:buy"` from the tuple:

```python
    for callback_data in (
        "menu:renew",
        "menu:myservices",
        "menu:tutorials",
    ):
```
(keep the rest of the function body unchanged.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_buy_flow.py`)
Expected: FAIL — `menu:buy` still answers "coming soon" via the placeholder handler; `buy:category:*` has no handler at all.

- [ ] **Step 3: Create the buy keyboards module**

`app/bot/keyboards/buy.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.services.catalog import format_price_usd


def buy_category_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Scroll", callback_data="buy:category:scroll")
    builder.button(text="🌊 Stream", callback_data="buy:category:stream")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


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

- [ ] **Step 4: Create the buy handler**

`app/bot/handlers/buy.py`:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.buy import buy_category_keyboard, buy_plan_keyboard
from app.db.session import async_session_maker
from app.services.catalog import list_plans

router = Router(name="buy")

_CATEGORY_TEXT = "🔑 <b>Buy Subscription</b>\n\nPick a category:"
_TIER_TEXT = "Pick a plan:"


@router.callback_query(F.data == "menu:buy")
async def buy_start_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(_CATEGORY_TEXT, reply_markup=buy_category_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("buy:category:"))
async def buy_category_cb(callback: CallbackQuery) -> None:
    category = callback.data.split(":")[-1]
    async with async_session_maker() as session:
        plans = await list_plans(session, category=category, active_only=True)
    if callback.message is not None:
        await callback.message.edit_text(_TIER_TEXT, reply_markup=buy_plan_keyboard(plans))
    await callback.answer()
```

- [ ] **Step 5: Wire the router into `app/main.py` and unblock `menu:buy`**

In `app/bot/handlers/users.py`, remove `"menu:buy"` from `_PLACEHOLDER_CALLBACKS`:

```python
_PLACEHOLDER_CALLBACKS = {
    "menu:renew",
    "menu:myservices",
    "menu:tutorials",
}
```

In `app/main.py`, change:
```python
from app.bot.handlers import (
    admin, admin_block, admin_discounts, admin_fallback, admin_renew, admin_settings,
    broadcast, fallback, trial, tutorial_admin, users,
)
```
to:
```python
from app.bot.handlers import (
    admin, admin_block, admin_discounts, admin_fallback, admin_renew, admin_settings,
    broadcast, buy, fallback, trial, tutorial_admin, users,
)
```

and change:
```python
    dp.include_router(admin_fallback.router)
    dp.include_router(users.router)
```
to:
```python
    dp.include_router(admin_fallback.router)
    dp.include_router(buy.router)
    dp.include_router(users.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_buy_flow.py`, and the updated `test_start_and_menu.py`.

- [ ] **Step 7: Commit**

```bash
git add app/bot/keyboards/buy.py app/bot/handlers/buy.py app/bot/handlers/users.py app/main.py \
        tests/functional/test_buy_flow.py tests/functional/test_start_and_menu.py
git commit -m "feat: buy subscription category and tier picker"
```

---

### Task 2: Price summary + auto-discount + payment-coming-soon wall

**Files:**
- Modify: `app/bot/keyboards/buy.py`
- Modify: `app/bot/handlers/buy.py`
- Test: `tests/functional/test_buy_flow.py`

**Interfaces:**
- Consumes: `catalog.get_plan(session, plan_id) -> Plan | None` (existing). `discounts.find_best_auto_discount(session, plan_id) -> DiscountCode | None`, `discounts.discount_price(original: Decimal, percent: Decimal) -> Decimal`, `discounts.create_discount_code` (existing, `app/services/discounts.py`, built in the Admin Panel plan for exactly this). `back_to_menu_keyboard()` from `app.bot.keyboards.trial` (existing, already reused by `app/bot/handlers/users.py`'s support handler — the established pattern for a generic "Back to Menu" screen).
- Produces: `buy_price_summary_keyboard(plan_id: int, category: str) -> InlineKeyboardMarkup` (`app/bot/keyboards/buy.py`) — nothing outside this task consumes it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_buy_flow.py`:

```python
def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_buy_plan_shows_price_summary_with_no_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "1 Month" in text
    assert "$5.00" in text
    assert "Duration: 30 days" in text
    assert "Data: 10 GB" in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "✅ Buy" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_plan_shows_auto_applied_public_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.db.session import async_session_maker
    from app.services.discounts import create_discount_code

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="WELCOME10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True
        )

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$4.50" in text
    assert "10" in text


@pytest.mark.asyncio
async def test_buy_plan_ignores_private_discount_codes(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.db.session import async_session_maker
    from app.services.discounts import create_discount_code

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="PRIVATE50", percent=Decimal("50"), usage_limit=None, plan_ids=[plan_id], is_public=False
        )

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$2.50" not in text


@pytest.mark.asyncio
async def test_buy_plan_not_found_shows_gone_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:plan:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_confirm_shows_coming_soon_and_creates_no_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from sqlalchemy import select

    from app.db.models.vpn_user import VPNUser
    from app.db.session import async_session_maker

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)

    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser))).scalars().all()
    assert list(rows) == []


@pytest.mark.asyncio
async def test_buy_confirm_not_found_shows_gone_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:confirm:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no longer exists" in edited[0][1]["text"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target the new tests in `tests/functional/test_buy_flow.py`)
Expected: FAIL — `buy:plan:*` and `buy:confirm:*` have no handler yet.

- [ ] **Step 3: Add the price-summary keyboard**

In `app/bot/keyboards/buy.py`, add below `buy_plan_keyboard`:

```python
def buy_price_summary_keyboard(plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Buy", callback_data=f"buy:confirm:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"buy:category:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Add the price-summary and confirm handlers**

In `app/bot/handlers/buy.py`, change the imports at the top to:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import buy_category_keyboard, buy_plan_keyboard, buy_price_summary_keyboard
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.session import async_session_maker
from app.services.catalog import format_price_usd, get_plan, list_plans
from app.services.discounts import discount_price, find_best_auto_discount
```

and add these constants and functions at the end of the file (after the existing `buy_category_cb`):

```python
_PLAN_GONE_TEXT = "⚠️ That plan no longer exists. Please pick another."
_COMING_SOON_TEXT = (
    "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
    "the moment they're live. No charge has been made and no account was created."
)


def _format_data_cap(data_cap_mb: int) -> str:
    if data_cap_mb % 1024 == 0:
        return f"{data_cap_mb // 1024} GB"
    return f"{data_cap_mb} MB"


async def _price_summary_text(session: AsyncSession, plan: Plan) -> str:
    lines = [
        f"🔑 <b>{plan.name} ({plan.category.title()})</b>",
        f"Duration: {plan.duration_days} days",
        f"Data: {_format_data_cap(plan.data_cap_mb)}",
    ]
    discount = await find_best_auto_discount(session, plan.id)
    if discount is not None:
        discounted = discount_price(plan.price_usd, discount.percent)
        lines.append(
            f"Price: <s>{format_price_usd(plan.price_usd)}</s> "
            f"{format_price_usd(discounted)} (-{discount.percent}%)"
        )
    else:
        lines.append(f"Price: {format_price_usd(plan.price_usd)}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("buy:plan:"))
async def buy_plan_cb(callback: CallbackQuery) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if plan is None:
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return
        text = await _price_summary_text(session, plan)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=buy_price_summary_keyboard(plan.id, plan.category))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
        await callback.answer()
        return
    if callback.message is not None:
        await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
    await callback.answer()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_buy_flow.py`, and the full suite green from a fresh state.

- [ ] **Step 6: Commit**

```bash
git add app/bot/keyboards/buy.py app/bot/handlers/buy.py tests/functional/test_buy_flow.py
git commit -m "feat: buy subscription price summary with auto-discount and payment-coming-soon wall"
```

---

## Self-Review

**Spec coverage** (`docs/superpowers/specs/2026-09-16-buy-subscription-design.md`):
- §2 Navigation (`buy:*` namespace, Back on every screen) → Tasks 1 and 2 together.
- §3 Category picker → Task 1.
- §4 Tier picker → Task 1.
- §5 Price summary (with auto-discount) → Task 2.
- §6 Payment-coming-soon wall → Task 2.
- §7 Out of scope (payment processing, account creation, typed discount codes, changes to other flows) → deliberately not built anywhere in this plan, matching the spec.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code; no test asserts a tautology.

**Type consistency check:**
- `buy_plan_keyboard(plans: list[Plan])` (Task 1) and `buy_price_summary_keyboard(plan_id: int, category: str)` (Task 2) are each called from exactly one place, with matching argument types.
- `_price_summary_text(session: AsyncSession, plan: Plan) -> str` (Task 2) matches its one call site in `buy_plan_cb`.
- Both `buy_plan_cb` and `buy_confirm_cb` (Task 2) use the identical `_PLAN_GONE_TEXT` + `back_to_menu_keyboard()` pattern for a missing plan — verified consistent between the two handlers.
