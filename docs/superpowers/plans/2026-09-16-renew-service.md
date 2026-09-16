# Renew Service (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the `menu:renew` placeholder with a service picker → category picker → tier picker → price-summary → "payment coming soon" flow, mirroring Buy Subscription's screens with an owned-service id threaded through every step.

**Architecture:** A new `app/bot/handlers/renew.py` router (with matching `app/bot/keyboards/renew.py`) reuses existing service-layer functions (`get_owned_vpn_user`, `list_vpn_users_for_telegram_id`, `list_plans`, `get_plan`, `find_best_auto_discount`, `discount_price`) exactly as Buy Subscription and My Services already do. No FSM state; every screen is reachable from ids embedded in colon-separated callback_data. No actual renewal is executed — this stays browsing-only until a real payment provider exists.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, PostgreSQL, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-16-renew-service-design.md`

## Global Constraints

- Every screen keyed by `vpn_user_id` MUST re-verify ownership via `get_owned_vpn_user(session, vpn_user_id, telegram_id)` before proceeding — not just the entry screen. A crafted callback naming another customer's service id must never reveal their plan or let them browse renewal pricing for it. (Spec §2.)
- `renew_and_change_group` (`app/services/vpn_users.py`) MUST NOT be called anywhere in this plan. The confirm screen only shows a "coming soon" message; no VPNUser row, no IBSng account, is ever mutated by this flow. (Spec §1, §7.)
- The Trial plan (`category == "trial"`) MUST be rejected on every plan-keyed screen (`renew:plan:*`, `renew:confirm:*`), the same way Buy's `_is_buyable` rejects it — Trial has no renewal concept and must never render a normal-looking renewal screen. (Spec §6.)
- Every int() parse of a callback_data segment MUST be guarded (try/except IndexError/ValueError falling back to the not-found screen) — callback_data is attacker-controlled, matching the hardening My Services' final review required for its own multi-segment handler.
- All catalog/generator-controlled interpolated text (plan names, `ibsng_group`, usernames) needs no `html.escape()` — matching the precedent set across Admin Panel, Buy Subscription, and My Services (only *typed* text needs it, and nothing in this flow accepts typed text).
- English-only user-facing text (project-wide convention, `CLAUDE.md`).

---

## File Structure

- **Modify** `app/services/vpn_users.py` — add `list_renewable_services(session, telegram_id) -> list[tuple[VPNUser, Plan | None]]`, placed near `list_services_with_status`.
- **Create** `app/bot/keyboards/renew.py` — all renew-flow keyboards: `renew_service_keyboard`, `renew_empty_keyboard`, `renew_category_keyboard`, `renew_plan_keyboard`, `renew_price_summary_keyboard`.
- **Create** `app/bot/handlers/renew.py` — the `renew` router: `menu:renew`, `renew:service:*`, `renew:category:*`, `renew:plan:*`, `renew:confirm:*`.
- **Modify** `app/bot/handlers/users.py` — remove `"menu:renew"` from `_PLACEHOLDER_CALLBACKS`.
- **Modify** `app/main.py` — register the new `renew` router, between `buy` and `myservices`.
- **Modify** `tests/functional/test_start_and_menu.py` — remove `"menu:renew"` from `test_placeholder_callbacks_answer_coming_soon`'s list.
- **Create** `tests/functional/test_renew_flow.py` — functional tests for the whole flow.

---

## Task 1: Service picker, category picker, tier picker

**Files:**
- Modify: `app/services/vpn_users.py`
- Create: `app/bot/keyboards/renew.py`
- Create: `app/bot/handlers/renew.py`
- Modify: `app/bot/handlers/users.py`
- Modify: `app/main.py`
- Modify: `tests/functional/test_start_and_menu.py`
- Create: `tests/functional/test_renew_flow.py`

**Interfaces:**
- Consumes: `get_owned_vpn_user(session, vpn_user_id, telegram_id) -> VPNUser | None`, `list_vpn_users_for_telegram_id(session, telegram_id) -> list[VPNUser]` (both `app/services/vpn_users.py`, already exist); `get_plan(session, plan_id) -> Plan | None`, `list_plans(session, *, category=None, active_only=True) -> list[Plan]`, `format_price_usd(price) -> str`, `format_data_cap(data_cap_mb: int) -> str`, `CATEGORIES` (all `app/services/catalog.py`, already exist); `back_to_menu_keyboard()` (`app/bot/keyboards/trial.py`, already exists — reused for the not-found screen, same as `myservices.py` does).
- Produces: `list_renewable_services(session, telegram_id) -> list[tuple[VPNUser, Plan | None]]` (`app/services/vpn_users.py`) — Task 2's price-summary screen does not need this directly, but the `renew` router it lives alongside does. `renew_service_keyboard(rows: list[tuple[VPNUser, Plan | None]]) -> InlineKeyboardMarkup`, `renew_empty_keyboard() -> InlineKeyboardMarkup`, `renew_category_keyboard(vpn_user_id: int) -> InlineKeyboardMarkup`, `renew_plan_keyboard(plans: list[Plan], vpn_user_id: int, category: str) -> InlineKeyboardMarkup` (all `app/bot/keyboards/renew.py`) — Task 2 adds `renew_price_summary_keyboard` to this same file. The `renew` router object (`app/bot/handlers/renew.py`) — Task 2 adds two more handlers to it.

- [ ] **Step 1: Write the failing test for `list_renewable_services`**

Add to `tests/functional/test_renew_flow.py` (new file):

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


async def _create_service(seeded_catalog: dict, *, telegram_id: int, category: str, name: str, is_trial: bool = False):
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client, telegram_id=telegram_id, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"], is_trial=is_trial,
        )
    return vpn_user


@pytest.mark.asyncio
async def test_list_renewable_services_excludes_trial(seeded_catalog: dict) -> None:
    from app.services.vpn_users import list_renewable_services

    telegram_id = 801
    paid = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)

    async with async_session_maker() as session:
        rows = await list_renewable_services(session, telegram_id)

    assert [vpn_user.id for vpn_user, _plan in rows] == [paid.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/functional/test_renew_flow.py::test_list_renewable_services_excludes_trial -v`
Expected: FAIL with `ImportError: cannot import name 'list_renewable_services'`

- [ ] **Step 3: Implement `list_renewable_services`**

In `app/services/vpn_users.py`, add this function directly after `list_services_with_status` (the last function in the file):

```python
async def list_renewable_services(session: AsyncSession, telegram_id: int) -> list[tuple[VPNUser, Plan | None]]:
    """Same shape as list_services_with_status but without the per-row
    IBSng status lookup (renewability doesn't depend on active/expired/
    pending) and with trial rows excluded - a trial has no paid plan to
    renew into, and Free Trial already has its own dedicated flow."""
    vpn_users = await list_vpn_users_for_telegram_id(session, telegram_id)
    rows: list[tuple[VPNUser, Plan | None]] = []
    for vpn_user in vpn_users:
        if vpn_user.is_trial:
            continue
        plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
        rows.append((vpn_user, plan))
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/functional/test_renew_flow.py::test_list_renewable_services_excludes_trial -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/vpn_users.py tests/functional/test_renew_flow.py
git commit -m "feat: add list_renewable_services for the renew flow"
```

- [ ] **Step 6: Write the failing tests for the service picker screen**

Append to `tests/functional/test_renew_flow.py`:

```python
@pytest.mark.asyncio
async def test_menu_renew_shows_empty_state_when_no_services(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(802, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "don't have any services" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔑 Buy Subscription" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_menu_renew_lists_non_trial_services_only(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 803
    paid = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    texts = [b["text"] for b in buttons]
    assert "1 Month" in texts
    assert not any("trial" in t.lower() for t in texts)
    callback_by_text = {b["text"]: b["callback_data"] for b in buttons}
    assert callback_by_text["1 Month"] == f"renew:service:{paid.id}"


@pytest.mark.asyncio
async def test_menu_renew_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(804, "menu:renew"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `pytest tests/functional/test_renew_flow.py -v`
Expected: FAIL — `menu:renew` is still in `_PLACEHOLDER_CALLBACKS`, so it answers "coming soon" instead of editing the message; `test_menu_renew_shows_empty_state_when_no_services` and `test_menu_renew_lists_non_trial_services_only` fail because no `editMessageText` call happens.

- [ ] **Step 8: Create `app/bot/keyboards/renew.py` with the service-picker keyboards**

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.services.catalog import format_data_cap, format_price_usd


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


def renew_category_keyboard(vpn_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Scroll", callback_data=f"renew:category:{vpn_user_id}:scroll")
    builder.button(text="🌊 Stream", callback_data=f"renew:category:{vpn_user_id}:stream")
    builder.button(text="⬅️ Back to Services", callback_data="menu:renew")
    builder.adjust(2, 1)
    return builder.as_markup()


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

- [ ] **Step 9: Create `app/bot/handlers/renew.py` with the service picker, category picker, and tier picker handlers**

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, get_plan, list_plans
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services

router = Router(name="renew")

_LIST_TEXT = "♻️ <b>Renew Service</b>\n\nWhich service do you want to renew?"
_EMPTY_TEXT = "♻️ <b>Renew Service</b>\n\nYou don't have any services to renew yet."
_NOT_FOUND_TEXT = "⚠️ Service not found."
_TIER_TEXT = "Pick a plan:"

# Trial has no renewal concept - it's excluded from every category/tier
# screen in this flow, same as Buy excludes it from its own.
_RENEW_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")


async def _not_found(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(_NOT_FOUND_TEXT, reply_markup=back_to_menu_keyboard())
    await callback.answer()


async def _service_display_name(session: AsyncSession, vpn_user: VPNUser) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    return plan.name if plan is not None else vpn_user.ibsng_group


@router.callback_query(F.data == "menu:renew")
async def renew_start_cb(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        rows = await list_renewable_services(session, telegram_id)

    if not rows:
        if callback.message is not None:
            await callback.message.edit_text(_EMPTY_TEXT, reply_markup=renew_empty_keyboard())
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(_LIST_TEXT, reply_markup=renew_service_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:service:"))
async def renew_service_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    try:
        vpn_user_id = int(parts[2])
    except (IndexError, ValueError):
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return
        name = await _service_display_name(session, vpn_user)

    text = f"♻️ <b>Renew {name}</b>\n\nPick a category:"
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=renew_category_keyboard(vpn_user_id))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:category:"))
async def renew_category_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    try:
        vpn_user_id = int(parts[2])
    except (IndexError, ValueError):
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return
        name = await _service_display_name(session, vpn_user)

        category = parts[3] if len(parts) > 3 else ""
        if category not in _RENEW_CATEGORIES:
            text = f"♻️ <b>Renew {name}</b>\n\nPick a category:"
            if callback.message is not None:
                await callback.message.edit_text(text, reply_markup=renew_category_keyboard(vpn_user_id))
            await callback.answer()
            return

        plans = await list_plans(session, category=category, active_only=True)

    if callback.message is not None:
        await callback.message.edit_text(_TIER_TEXT, reply_markup=renew_plan_keyboard(plans, vpn_user_id, category))
    await callback.answer()
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `pytest tests/functional/test_renew_flow.py -v`
Expected: still FAIL for the three Step 6 tests — the router isn't registered yet and `menu:renew` is still in `_PLACEHOLDER_CALLBACKS`, which is registered on a router that runs before `renew` would be in the dispatcher, so it still wins. Continue to Steps 11-12.

- [ ] **Step 11: Wire the router in and remove the placeholder**

In `app/bot/handlers/users.py`, change:

```python
_PLACEHOLDER_CALLBACKS = {
    "menu:renew",
    "menu:tutorials",
}
```

to:

```python
_PLACEHOLDER_CALLBACKS = {
    "menu:tutorials",
}
```

In `app/main.py`, add `renew` to the import block:

```python
from app.bot.handlers import (
    admin, admin_block, admin_discounts, admin_fallback, admin_renew, admin_settings,
    broadcast, buy, fallback, myservices, renew, trial, tutorial_admin, users,
)
```

and register it between `buy` and `myservices`:

```python
    dp.include_router(buy.router)
    dp.include_router(renew.router)
    dp.include_router(myservices.router)
```

- [ ] **Step 12: Run the full test suite**

Run: `make test`
Expected: PASS — including the three Step 6 tests, `test_placeholder_callbacks_answer_coming_soon` in `test_start_and_menu.py` (still asserts `"menu:tutorials"` alone works — unaffected by this change since that test doesn't reference `"menu:renew"` after Step 13), and `test_start_shows_english_main_menu`.

- [ ] **Step 13: Update the placeholder test**

In `tests/functional/test_start_and_menu.py`, change:

```python
async def test_placeholder_callbacks_answer_coming_soon(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    for callback_data in (
        "menu:renew",
        "menu:tutorials",
    ):
```

to:

```python
async def test_placeholder_callbacks_answer_coming_soon(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    for callback_data in (
        "menu:tutorials",
    ):
```

- [ ] **Step 14: Write the remaining Task 1 tests — category picker, tier picker, IDOR, malformed ids**

Append to `tests/functional/test_renew_flow.py`:

```python
def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_renew_service_shows_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 805
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Renew 1 Month" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🌊 Stream" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_service_unknown_id_shows_not_found(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(806, "renew:service:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_service_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 807
    intruder_id = 808
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_service_malformed_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(809, "renew:service:not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_category_shows_scroll_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 810
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:category:{service.id}:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    buttons = [b["text"] for b in all_buttons]
    assert "2 Weeks — $3.00 (5 GB)" in buttons
    assert "1 Month — $5.00 (10 GB)" in buttons
    assert "2 Months — $9.00 (20 GB)" in buttons

    callback_data_by_text = {b["text"]: b["callback_data"] for b in all_buttons}
    for name in ("2 Weeks", "1 Month", "2 Months"):
        plan_id = _plan_id(seeded_catalog, category="scroll", name=name)
        matching = next(cb for text, cb in callback_data_by_text.items() if text.startswith(f"{name} — "))
        assert matching == f"renew:plan:{service.id}:{plan_id}"


@pytest.mark.asyncio
async def test_renew_category_invalid_category_redirects_to_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 811
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:category:{service.id}:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Pick a category" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🌊 Stream" in buttons


@pytest.mark.asyncio
async def test_renew_category_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 812
    intruder_id = 813
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:category:{service.id}:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()
```

- [ ] **Step 15: Run the full test suite**

Run: `make test`
Expected: PASS, all tests including the new ones from Step 14.

- [ ] **Step 16: Commit**

```bash
git add app/bot/keyboards/renew.py app/bot/handlers/renew.py app/bot/handlers/users.py app/main.py \
        tests/functional/test_renew_flow.py tests/functional/test_start_and_menu.py
git commit -m "feat: renew service picker, category picker, and tier picker"
```

---

## Task 2: Price summary and "coming soon" confirm screen

**Files:**
- Modify: `app/bot/keyboards/renew.py`
- Modify: `app/bot/handlers/renew.py`
- Modify: `tests/functional/test_renew_flow.py`

**Interfaces:**
- Consumes: `_RENEW_CATEGORIES`, `_not_found`, `_service_display_name`, `router` (all `app/bot/handlers/renew.py`, from Task 1); `find_best_auto_discount(session, plan_id) -> DiscountCode | None`, `discount_price(original, percent) -> Decimal` (`app/services/discounts.py`, already exist); `format_price_usd`, `format_data_cap` (`app/services/catalog.py`, already exist).
- Produces: `renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str) -> InlineKeyboardMarkup` (`app/bot/keyboards/renew.py`). No later task consumes this — it's the terminal screen.

- [ ] **Step 1: Write the failing tests for the price summary screen**

Append to `tests/functional/test_renew_flow.py`:

```python
@pytest.mark.asyncio
async def test_renew_plan_shows_price_summary_with_no_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 820
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "1 Month" in text
    assert "$5.00" in text
    assert "Duration: 30 days" in text
    assert "Data: 10 GB" in text
    assert "<s>" not in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "✅ Renew" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_plan_shows_auto_applied_public_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.services.discounts import create_discount_code

    telegram_id = 821
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="WELCOME10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True
        )

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$4.50" in text
    assert "-10%" in text


@pytest.mark.asyncio
async def test_renew_plan_not_found_shows_gone_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 822
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_plan_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 823
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 824
    intruder_id = 825
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_malformed_plan_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 826
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_renew_flow.py -k renew_plan -v`
Expected: FAIL — no handler matches `renew:plan:*` yet, so `menu_root_cb`/`fallback` handles it (or nothing matches and the test's `editMessageText` assertion finds zero calls).

- [ ] **Step 3: Add `renew_price_summary_keyboard` to `app/bot/keyboards/renew.py`**

Append to the end of `app/bot/keyboards/renew.py`:

```python
def renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Renew", callback_data=f"renew:confirm:{vpn_user_id}:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"renew:category:{vpn_user_id}:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Add the price summary handler to `app/bot/handlers/renew.py`**

Update the imports at the top of `app/bot/handlers/renew.py` — change:

```python
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, get_plan, list_plans
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services
```

to:

```python
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_price_summary_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, format_data_cap, format_price_usd, get_plan, list_plans
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services
```

Add these constants near the top, next to `_TIER_TEXT`:

```python
_PLAN_GONE_TEXT = "⚠️ That plan no longer exists. Please pick another."
```

Add this helper function and handler at the end of the file:

```python
def _is_renewable(plan: Plan | None) -> bool:
    """Trial is a real, $0.00 plan - Renew must never expose it, same
    reasoning as Buy's own _is_buyable."""
    return plan is not None and plan.category != "trial"


async def _renew_summary_text(session: AsyncSession, current_name: str, plan: Plan) -> str:
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


@router.callback_query(F.data.startswith("renew:plan:"))
async def renew_plan_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    try:
        vpn_user_id = int(parts[2])
        plan_id = int(parts[3])
    except (IndexError, ValueError):
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return

        plan = await get_plan(session, plan_id)
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

        current_name = await _service_display_name(session, vpn_user)
        text = await _renew_summary_text(session, current_name, plan)

    if callback.message is not None:
        await callback.message.edit_text(
            text, reply_markup=renew_price_summary_keyboard(vpn_user_id, plan.id, plan.category)
        )
    await callback.answer()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/functional/test_renew_flow.py -k renew_plan -v`
Expected: PASS

- [ ] **Step 6: Write the failing tests for the confirm screen**

Append to `tests/functional/test_renew_flow.py`:

```python
@pytest.mark.asyncio
async def test_renew_confirm_shows_coming_soon_and_does_not_mutate_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from app.services.ibsng.client import IBSngClient

    telegram_id = 827
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    original_group = service.ibsng_group
    original_plan_id = service.plan_id
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)

    async with async_session_maker() as session:
        refreshed = await session.get(type(service), service.id)
    assert refreshed.ibsng_group == original_group
    assert refreshed.plan_id == original_plan_id

    async with IBSngClient() as client:
        live_group = await client.get_user_group(username=service.ibsng_username)
    assert live_group == original_group


@pytest.mark.asyncio
async def test_renew_confirm_not_found_shows_gone_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 828
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 829
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 830
    intruder_id = 831
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:confirm:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_malformed_ids_degrade_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(832, "renew:confirm:not-a-number:also-not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `pytest tests/functional/test_renew_flow.py -k renew_confirm -v`
Expected: FAIL — no `renew:confirm:*` handler exists yet.

- [ ] **Step 8: Add the confirm handler to `app/bot/handlers/renew.py`**

Add this constant near `_PLAN_GONE_TEXT`:

```python
_COMING_SOON_TEXT = (
    "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
    "the moment they're live. No charge has been made and your service has not "
    "been changed."
)
```

Add this handler at the end of the file:

```python
@router.callback_query(F.data.startswith("renew:confirm:"))
async def renew_confirm_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    try:
        vpn_user_id = int(parts[2])
        plan_id = int(parts[3])
    except (IndexError, ValueError):
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return

        plan = await get_plan(session, plan_id)
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

    # renew_and_change_group is deliberately never called here - no
    # renewal is executed until a real payment provider exists (spec §7).
    if callback.message is not None:
        await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
    await callback.answer()
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/functional/test_renew_flow.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 10: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green.

- [ ] **Step 11: Commit**

```bash
git add app/bot/keyboards/renew.py app/bot/handlers/renew.py tests/functional/test_renew_flow.py
git commit -m "feat: renew price summary and payment-coming-soon confirm screen"
```

---

## Self-Review

**1. Spec coverage:**
- §1 (Summary, service-reuse rationale) — Task 1 Step 3 reuses `list_vpn_users_for_telegram_id`/`get_plan`; §7's "never call `renew_and_change_group`" is a Global Constraint and Task 2 Step 8's handler comment states it's deliberately absent. Covered.
- §2 (Navigation, callback-data map, ownership re-verification on every screen) — all five callback shapes implemented (Task 1 Steps 9/11, Task 2 Steps 4/8); every handler calls `get_owned_vpn_user` before proceeding. Covered.
- §3 (Service picker, `list_renewable_services`) — Task 1 Steps 1-5. Covered.
- §4 (Category picker) — Task 1 Step 9 (`renew_service_cb`). Covered.
- §5 (Tier picker, category validation) — Task 1 Step 9 (`renew_category_cb`, `_RENEW_CATEGORIES`). Covered.
- §6 (Price summary, discount reuse, trial rejection) — Task 2 Steps 3-4. Covered.
- §7 (Confirm screen, coming-soon text, no mutation) — Task 2 Step 8. Covered.
- §8 (Main menu wiring) — Task 1 Steps 11-13. Covered.
- §9 (Out of scope) — no task calls `renew_and_change_group`, no typed discount entry, no current-plan highlighting; matches.

**2. Placeholder scan:** No "TBD"/"TODO"/"similar to Buy" patterns — every step's code is complete and specific to this feature (adapted from Buy/My Services' actual current source, not referenced by pointer).

**3. Type consistency:** `list_renewable_services(session, telegram_id) -> list[tuple[VPNUser, Plan | None]]` (Task 1) matches its only two call sites — `renew_start_cb` (Task 1) and `renew_service_keyboard` (Task 1) — both typed identically. `renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str)` (Task 2 Step 3) matches its one call site in `renew_plan_cb` (Task 2 Step 4), called with `(vpn_user_id, plan.id, plan.category)` — `plan.id`/`plan.category` are `int`/`str` per the existing `Plan` model, matching the signature. `_is_renewable` (Task 2) mirrors `_is_buyable`'s signature and return type exactly (`Plan | None -> bool`). `_service_display_name`/`_not_found` are defined once in Task 1 and reused as-is in Task 2 (same module, no re-declaration) — no signature drift possible.
