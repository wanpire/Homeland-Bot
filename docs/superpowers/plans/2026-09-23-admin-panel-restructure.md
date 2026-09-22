# Admin Panel Restructure Implementation Plan (Epic Part 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regroup the admin panel into seven top-level entries, adding Financial and Reports, without renaming a single callback.

**Architecture:** Keyboards decide what is listed where; handlers and routers are untouched except for two new menu handlers and six Back destinations. Every existing `adm:*` callback keeps working, so keyboards already sitting in an admin's chat history stay live.

**Tech Stack:** Python 3.12, aiogram 3.x, pytest in the isolated Docker stack.

**Spec:** `docs/superpowers/specs/2026-09-23-admin-panel-restructure-design.md`

## Global Constraints

- **No callback may be renamed, removed or repurposed in this part.** The only permitted changes are which keyboard lists a button and where a Back button points.
- Admin-facing text stays English and never goes through `t()`.
- A button a tier cannot use is **hidden**, never shown-and-filtered, matching the Broadcast precedent.
- `admin_fallback.router` stays registered last in `build_dispatcher`.
- Thin handlers, async only, type hints on every signature.
- Run the suite with `make test`, or against the running stack: `docker exec homeland_bot_test-test-runner-1 sh -c 'rm -rf /app/app /app/tests'`, `tar --exclude=.git --exclude=.claude -cf - app tests | docker exec -i homeland_bot_test-test-runner-1 tar -xf - -C /app`, `docker exec homeland_bot_test-db_test-1 psql -U homeland_test -d homeland_test -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`, then `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/ -q`.

---

## File Structure

- **Modify** `app/bot/keyboards/admin.py` — rebuild `admin_root_menu`, add `admin_financial_menu`, trim `admin_settings_menu`.
- **Modify** `app/bot/handlers/admin.py` — add `adm:fin` and `adm:reports` handlers.
- **Modify** `app/bot/keyboards/admin_discounts.py`, `manage_plans.py`, `crypto_settlement.py`, `admin_admins.py` — Back destinations.
- **Modify** `app/bot/handlers/admin_settings.py` — Back destinations on Crypto Coins and Recover Stuck Payments.
- **Modify** `tests/functional/test_admin_panel_root.py`; **create** `tests/functional/test_admin_financial_menu.py`.

---

## Task 1: The new tree

**Files:**
- Modify: `app/bot/keyboards/admin.py`, `app/bot/handlers/admin.py`
- Test: `tests/functional/test_admin_panel_root.py`, `tests/functional/test_admin_financial_menu.py`

**Interfaces:**
- Produces: `admin_financial_menu(*, is_full_admin: bool) -> InlineKeyboardMarkup`; callbacks `adm:fin` and `adm:reports`.

- [ ] **Step 1: Write the failing tests**

Replace the root-menu assertions in `tests/functional/test_admin_panel_root.py` and add `tests/functional/test_admin_financial_menu.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


def _buttons(fake_session: FakeBotSession) -> dict[str, str]:
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    markup = edited[-1][1].get("reply_markup") or {"inline_keyboard": []}
    return {b["text"]: b["callback_data"] for row in markup["inline_keyboard"] for b in row}


@pytest.mark.asyncio
async def test_financial_menu_lists_every_money_screen_for_a_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin"))

    buttons = _buttons(fake_session)
    assert buttons["🏷 Discount Codes"] == "adm:discounts"
    assert buttons["💰 Manage Plans"] == "adm:settings:plans"
    assert buttons["💳 Crypto Settlement Address"] == "adm:settings:crypto"
    assert buttons["💱 Crypto Coins"] == "adm:settings:coins"
    assert buttons["🔄 Recover Stuck Payments"] == "adm:settings:reconcile"
    assert any("back" in text.lower() for text in buttons)


@pytest.mark.asyncio
async def test_financial_menu_hides_full_only_screens_from_a_sales_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A visible button whose router filter rejects the tap gives zero
    feedback - the same reason Broadcast is hidden rather than gated."""
    await _seed_admin(880, "sales")

    await dispatcher.feed_update(bot, make_callback_update(880, "adm:fin"))

    buttons = _buttons(fake_session)
    assert "🏷 Discount Codes" in buttons
    assert "💰 Manage Plans" in buttons
    for full_only in ("💳 Crypto Settlement Address", "💱 Crypto Coins", "🔄 Recover Stuck Payments"):
        assert full_only not in buttons


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["adm:fin", "adm:reports"])
async def test_support_admin_is_refused_financial_and_reports(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    await _seed_admin(881, "support")

    await dispatcher.feed_update(bot, make_callback_update(881, data))

    assert not [c for c in fake_session.calls if c[0] == "editMessageText"]
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    ["adm:discounts", "adm:settings:plans", "adm:settings:crypto", "adm:settings:coins", "adm:admins"],
)
async def test_moved_screens_are_still_reachable_by_their_original_callback(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    """A keyboard sitting in an admin's chat history is a live control
    surface: tapping last week's panel must still work."""
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, data))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited, f"{data} rendered nothing"
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("permission" in (c[1].get("text") or "").lower() for c in answered)
```

In `test_admin_panel_root.py`, update the root-menu expectations to the seven entries, and assert that Discount Codes and Manage Admins are **no longer** at the top level.

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_admin_financial_menu.py -q`
Expected: FAIL — `adm:fin` falls through to `admin_fallback`'s permission alert.

- [ ] **Step 3: Rebuild the keyboards**

In `app/bot/keyboards/admin.py`:

```python
def admin_root_menu(*, is_sales_admin: bool, is_full_admin: bool) -> InlineKeyboardMarkup:
    """Seven entries, grouped by what an admin is trying to do rather
    than by the order features happened to ship in. A button a tier
    cannot use is hidden, never shown-and-filtered: Telegram gives no
    feedback when a filter silently rejects a tap."""
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    builder.button(text="👤 Users", callback_data="adm:users")
    sizes.append(1)
    if is_sales_admin:
        builder.button(text="💰 Financial", callback_data="adm:fin")
        builder.button(text="📊 Reports", callback_data="adm:reports")
        sizes.append(2)
    builder.button(text="📚 Tutorials & Profiles", callback_data="adm:tutorials")
    sizes.append(1)
    if is_full_admin:
        builder.button(text="📢 Broadcast", callback_data="adm:broadcast")
        builder.button(text="⚙️ System", callback_data="adm:settings")
        sizes.append(2)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    sizes.append(1)

    builder.adjust(*sizes)
    return builder.as_markup()


def admin_financial_menu(*, is_full_admin: bool) -> InlineKeyboardMarkup:
    """Revenue and Payments are Part 2 of the admin epic; the rest moved
    here from the root menu and Settings, keeping their callbacks."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Revenue Overview", callback_data="adm:fin:revenue")
    builder.button(text="🧾 Payments", callback_data="adm:fin:payments")
    builder.button(text="🏷 Discount Codes", callback_data="adm:discounts")
    builder.button(text="💰 Manage Plans", callback_data="adm:settings:plans")
    if is_full_admin:
        builder.button(text="💳 Crypto Settlement Address", callback_data="adm:settings:crypto")
        builder.button(text="💱 Crypto Coins", callback_data="adm:settings:coins")
        builder.button(text="🔄 Recover Stuck Payments", callback_data="adm:settings:reconcile")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

and trim `admin_settings_menu` to Support Contact, Sync IBSng Groups, Mandatory Channel, Renewal Reminders, Trial Limit, Manage Admins, Back to Admin Panel.

- [ ] **Step 4: Add the two handlers**

In `app/bot/handlers/admin.py`, alongside the existing ones (this router carries no router-level filter because it serves every tier, so each handler gates itself):

```python
_FINANCIAL_TEXT = "💰 <b>Financial</b>"
_REPORTS_TEXT = (
    "📊 <b>Reports</b>\n\n"
    "Signups, active accounts, revenue, trial conversion and top plans "
    "arrive in Part 4 of the admin epic."
)


@router.callback_query(F.data == "adm:fin")
async def admin_financial_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "sales"):
            await callback.answer()
            return
        is_full = await has_level(session, callback.from_user.id, "full")
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(
            _FINANCIAL_TEXT, reply_markup=admin_financial_menu(is_full_admin=is_full)
        )
    await callback.answer()


@router.callback_query(F.data == "adm:reports")
async def admin_reports_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "sales"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_REPORTS_TEXT, reply_markup=back_to_admin_root_keyboard())
    await callback.answer()
```

Note the early `await callback.answer()` with no text on refusal: that is the existing convention in this router, and `admin_fallback` is what produces the visible permission alert, since it claims any `adm:*` nothing else answered. Add a small `back_to_admin_root_keyboard()` to `admin.py`'s keyboards if none exists, and rename `_SETTINGS_TEXT` to read "⚙️ <b>System</b>".

- [ ] **Step 5: Run**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_admin_financial_menu.py tests/functional/test_admin_panel_root.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/bot/keyboards/admin.py app/bot/handlers/admin.py tests
git commit -m "feat: group the admin panel into Users, Financial, Reports, Content, Broadcast, System"
```

---

## Task 2: Back destinations follow the moves

**Files:**
- Modify: `app/bot/keyboards/admin_discounts.py`, `manage_plans.py`, `crypto_settlement.py`, `admin_admins.py`, `app/bot/handlers/admin_settings.py`
- Test: `tests/functional/test_admin_financial_menu.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "parent"),
    [
        ("adm:discounts", "adm:fin"),
        ("adm:settings:plans", "adm:fin"),
        ("adm:settings:crypto", "adm:fin"),
        ("adm:settings:coins", "adm:fin"),
        ("adm:settings:reconcile", "adm:fin"),
        ("adm:admins", "adm:settings"),
    ],
)
async def test_moved_screens_go_back_to_their_new_parent(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str, parent: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, data))

    assert parent in set(_buttons(fake_session).values())
```

`adm:settings:reconcile` runs a live Plisio sweep, so monkeypatch `admin_settings.reconcile_pending_payments` to return zeroed counts in that case.

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL for every row — each screen still points at its old parent.

- [ ] **Step 3: Repoint the Back buttons**

One line each: `adm:root` → `adm:fin` in `admin_discounts.py`'s list keyboard; `adm:settings` → `adm:fin` in `manage_plans.py`, `crypto_settlement.py` (both keyboards) and `admin_settings.py`'s Crypto Coins and Recover Stuck Payments screens, which use the shared `back_to_settings_keyboard()` — give those two their own `back_to_financial_keyboard()` rather than repointing the shared one, since the other Settings screens still belong to System; and `adm:root` → `adm:settings` in `admin_admins.py`.

- [ ] **Step 4: Run the full suite**

Run: `make test`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/bot tests
git commit -m "feat: moved admin screens return to their new parent menu"
```

---

## Task 3: Docs and deploy

- [ ] **Step 1: CLAUDE.md**

Record the tree and the rule that no `adm:*` callback is ever renamed, only re-parented, because stale keyboards in chat history stay live.

- [ ] **Step 2: Deploy**

```bash
git push origin main
ssh homeland-bot-server 'cd ~/Homeland-Bot && git pull --ff-only && docker compose up -d --build && docker compose logs --tail=10 bot'
```

- [ ] **Step 3: Verify**

Open the panel: seven entries. Check Financial lists five screens, System lists six, and an old keyboard scrolled up in the chat still opens Discount Codes.

---

## Self-Review

- **Spec coverage:** §2 tree → Task 1; §3 compatibility → Task 1 Step 1's reachability test plus the no-rename constraint; §4 tiers → Task 1 Steps 3–4 and their tests; §5 shape → Tasks 1–2; §6 tests → Tasks 1–2.
- **Placeholder scan:** Task 2 Step 3 describes six one-line edits rather than quoting each file; every new function and handler is given in full. Revenue and Payments are deliberately dead buttons until Part 2, which the Reports text states plainly.
- **Type consistency:** `admin_financial_menu(*, is_full_admin: bool)` matches its single call site; `admin_root_menu(*, is_sales_admin, is_full_admin)` keeps its existing signature so every caller is unaffected.
