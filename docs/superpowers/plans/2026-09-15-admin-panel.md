# Admin Panel (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tier-gated admin panel (`adm:*` navigation, broadcast, block/unblock, admin renew-by-username, discount codes, support-contact + IBSng group sync settings) on top of Homeland's existing bootstrap + trial/tutorial-delivery foundation.

**Architecture:** One new router + keyboard module + (state module where the flow is multi-step) per admin section, all wired into `app/main.py`'s `build_dispatcher`. Two new `BaseFilter` classes (`IsSalesAdmin`, `IsFullAdmin`) gate sales/full-only routers at the router level; support-level sections do an inline `has_level(..., "support")` check, matching the existing `tutorial_admin.py` convention. The only new domain logic is `IBSngClient.renew_user`, `vpn_users.renew_and_change_group`, and the `DiscountCode` model/service — everything else is UI wrapping already-existing services.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, Alembic, pytest+pytest-asyncio (same as the rest of the repo).

**Spec:** `docs/superpowers/specs/2026-09-15-admin-panel-design.md`

## Global Constraints

- Async only — no blocking I/O in handlers or services (CLAUDE.md).
- Type hints on every function signature (CLAUDE.md).
- All user-facing AND admin-facing strings in English (CLAUDE.md).
- IBSng operations (create/renew/change user) must be idempotent (CLAUDE.md) — `renew_user` clears an attribute via `to_del_attrs`, a no-op if already absent.
- Keep handlers thin: parse input, call a service, reply (CLAUDE.md).
- New feature = new router + new service method, not a growing god-file (CLAUDE.md).
- Every interactive flow/menu includes a "Back" or "Cancel" button by default (CLAUDE.md).
- `app/main.py`'s `build_dispatcher(storage)` is the single source of truth for router wiring — both production and `tests/conftest.py`'s `dispatcher` fixture call it. Never duplicate wiring elsewhere.
- Callback-data namespace is `adm:*`, colon-separated path segments (spec §3).
- Router-level tier gating uses the two new filters (`IsSalesAdmin`, `IsFullAdmin`); support-level gating is an inline `has_level(session, telegram_id, "support")` check per handler (spec §2).
- Any handler that can be reached mid-flow from elsewhere (a "Back"/"Cancel" button, a stale message) must clear FSM state when navigating away from a flow, so a later plain-text message is never swallowed by a stale state's handler.

---

## File Structure

New files:
- `app/bot/filters/__init__.py` — empty, makes `app/bot/filters` a package.
- `app/bot/filters/admin.py` — `IsSalesAdmin`, `IsFullAdmin` filters.
- `app/bot/keyboards/admin.py` — root menu, users submenu, settings submenu keyboards.
- `app/bot/handlers/admin.py` — `adm:root` / `adm:users` / `adm:settings` / `adm:tutorials` navigation handlers.
- `app/bot/states/broadcast.py`, `app/bot/keyboards/broadcast.py`, `app/bot/handlers/broadcast.py` — broadcast flow.
- `app/bot/states/admin_block.py`, `app/bot/keyboards/admin_block.py`, `app/bot/handlers/admin_block.py` — block/unblock UI.
- `app/bot/states/admin_renew.py`, `app/bot/keyboards/admin_renew.py`, `app/bot/handlers/admin_renew.py` — admin renew-by-username.
- `app/db/models/discount_code.py`, `alembic/versions/0006_discount_codes.py`, `app/services/discounts.py` — discount code model/schema/service.
- `app/bot/states/admin_discounts.py`, `app/bot/keyboards/admin_discounts.py`, `app/bot/handlers/admin_discounts.py` — discount code admin CRUD flow.
- `app/bot/states/admin_settings.py`, `app/bot/keyboards/admin_settings.py`, `app/bot/handlers/admin_settings.py` — support contact + IBSng group sync.

Modified files:
- `app/bot/handlers/users.py` — remove `"adm:root"` from `_PLACEHOLDER_CALLBACKS` (Task 1).
- `app/main.py` — register each new router (every task except Task 5).
- `app/services/ibsng/client.py` — add `renew_user` (Task 4).
- `app/services/vpn_users.py` — add `renew_and_change_group` (Task 4).
- `app/db/models/__init__.py` — export `DiscountCode` (Task 5).
- `app/services/bot_users.py` — add `list_blocked_users` (Task 3).
- `tests/fakes/fake_bot_session.py` — add `blocked_chat_ids` to simulate `TelegramForbiddenError` (Task 2).
- `tests/functional/test_start_and_menu.py` — drop `"adm:root"` from the placeholder-callback test (Task 1).
- `tests/functional/test_ibsng_client.py`, `tests/functional/test_vpn_users.py` — add renew coverage (Task 4).

---

### Task 1: Auth filters + navigation shell

**Files:**
- Create: `app/bot/filters/__init__.py`
- Create: `app/bot/filters/admin.py`
- Create: `app/bot/keyboards/admin.py`
- Create: `app/bot/handlers/admin.py`
- Modify: `app/bot/handlers/users.py`
- Modify: `app/main.py`
- Modify: `tests/functional/test_start_and_menu.py`
- Test: `tests/functional/test_admin_panel_root.py`

**Interfaces:**
- Produces: `IsSalesAdmin`, `IsFullAdmin` (both `aiogram.filters.BaseFilter` subclasses, `app/bot/filters/admin.py`) — later tasks apply these at router level via `router.message.filter(...)` / `router.callback_query.filter(...)`. `admin_root_menu(*, is_sales_admin: bool, is_full_admin: bool) -> InlineKeyboardMarkup`, `admin_users_menu() -> InlineKeyboardMarkup`, `admin_settings_menu() -> InlineKeyboardMarkup` (`app/bot/keyboards/admin.py`) — later tasks' "Back" buttons target `adm:root` / `adm:users` / `adm:settings`, all owned by this task's router.
- Consumes: `has_level(session, telegram_id, min_level)` from `app.services.admin_users` (existing). `tutorial_admin_root_keyboard()` from `app.bot.keyboards.tutorial_admin` (existing).

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_admin_panel_root.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


def _buttons(fake_session: FakeBotSession) -> list[str]:
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    markup = edited[-1][1]["reply_markup"]
    return [b["text"] for row in markup["inline_keyboard"] for b in row]


@pytest.mark.asyncio
async def test_non_admin_gets_no_admin_root_screen(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "adm:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert len(answered) == 1


@pytest.mark.asyncio
async def test_support_admin_sees_root_menu_without_sales_or_full_buttons(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_admin(601, "support")

    await dispatcher.feed_update(bot, make_callback_update(601, "adm:root"))

    buttons = _buttons(fake_session)
    assert "📢 Broadcast" in buttons
    assert "👤 Users" in buttons
    assert "📚 Tutorials & Profiles" in buttons
    assert "🏷 Discount Codes" not in buttons
    assert "⚙️ Settings" not in buttons


@pytest.mark.asyncio
async def test_sales_admin_sees_discounts_but_not_settings(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_admin(602, "sales")

    await dispatcher.feed_update(bot, make_callback_update(602, "adm:root"))

    buttons = _buttons(fake_session)
    assert "🏷 Discount Codes" in buttons
    assert "⚙️ Settings" not in buttons


@pytest.mark.asyncio
async def test_full_admin_sees_every_section(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:root"))

    buttons = _buttons(fake_session)
    assert "🏷 Discount Codes" in buttons
    assert "⚙️ Settings" in buttons


@pytest.mark.asyncio
async def test_adm_users_submenu_shows_renew_and_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_admin(603, "support")

    await dispatcher.feed_update(bot, make_callback_update(603, "adm:users"))

    buttons = _buttons(fake_session)
    assert "♻️ Renew a Service" in buttons
    assert "🚫 Blocked Users" in buttons


@pytest.mark.asyncio
async def test_adm_settings_requires_full_admin(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_admin(604, "sales")

    await dispatcher.feed_update(bot, make_callback_update(604, "adm:settings"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings"))
    buttons = _buttons(fake_session)
    assert "☎️ Support Contact" in buttons
    assert "🔄 Sync IBSng Groups" in buttons


@pytest.mark.asyncio
async def test_adm_tutorials_adapter_matches_admintutorials_command(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))
    command_text = [c for c in fake_session.calls if c[0] == "sendMessage"][-1][1]["text"]

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:tutorials"))
    adapter_text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]

    assert adapter_text == command_text
```

Also edit `tests/functional/test_start_and_menu.py`'s `test_placeholder_callbacks_answer_coming_soon`: remove the comment about `"adm:root"` and drop it from the tuple, since it now has a real handler:

```python
@pytest.mark.asyncio
async def test_placeholder_callbacks_answer_coming_soon(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    for callback_data in (
        "menu:buy",
        "menu:renew",
        "menu:myservices",
        "menu:tutorials",
    ):
```
(keep the rest of the function body unchanged.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (or `pytest tests/functional/test_admin_panel_root.py -v` inside the test container)
Expected: FAIL — `adm:root`/`adm:users`/`adm:settings`/`adm:tutorials` still have no real handler, so `editMessageText` never fires.

- [ ] **Step 3: Create the filters module**

`app/bot/filters/__init__.py` — empty file.

`app/bot/filters/admin.py`:

```python
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.db.session import async_session_maker
from app.services.admin_users import has_level


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

- [ ] **Step 4: Create the admin keyboards module**

`app/bot/keyboards/admin.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_root_menu(*, is_sales_admin: bool, is_full_admin: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Broadcast", callback_data="adm:broadcast")
    builder.button(text="👤 Users", callback_data="adm:users")
    builder.button(text="📚 Tutorials & Profiles", callback_data="adm:tutorials")
    sizes = [1, 1, 1]
    if is_sales_admin:
        builder.button(text="🏷 Discount Codes", callback_data="adm:discounts")
        sizes.append(1)
    if is_full_admin:
        builder.button(text="⚙️ Settings", callback_data="adm:settings")
        sizes.append(1)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    sizes.append(1)
    builder.adjust(*sizes)
    return builder.as_markup()


def admin_users_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="♻️ Renew a Service", callback_data="adm:users:renew")
    builder.button(text="🚫 Blocked Users", callback_data="adm:users:blocked:0")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()


def admin_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Create the admin navigation handler**

`app/bot/handlers/admin.py`:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.keyboards.admin import admin_root_menu, admin_settings_menu, admin_users_menu
from app.bot.keyboards.tutorial_admin import tutorial_admin_root_keyboard
from app.db.session import async_session_maker
from app.services.admin_users import has_level

router = Router(name="admin")

_ROOT_TEXT = "🛠 <b>Admin Panel</b>"
_USERS_TEXT = "👤 <b>Users</b>"
_SETTINGS_TEXT = "⚙️ <b>Settings</b>"
_TUTORIALS_TEXT = "📚 Tutorials & Profiles admin:"


@router.callback_query(F.data == "adm:root")
async def admin_root_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "support"):
            await callback.answer()
            return
        is_sales = await has_level(session, callback.from_user.id, "sales")
        is_full = await has_level(session, callback.from_user.id, "full")
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(
            _ROOT_TEXT, reply_markup=admin_root_menu(is_sales_admin=is_sales, is_full_admin=is_full)
        )
    await callback.answer()


@router.callback_query(F.data == "adm:users")
async def admin_users_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "support"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_USERS_TEXT, reply_markup=admin_users_menu())
    await callback.answer()


@router.callback_query(F.data == "adm:settings")
async def admin_settings_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "full"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_SETTINGS_TEXT, reply_markup=admin_settings_menu())
    await callback.answer()


@router.callback_query(F.data == "adm:tutorials")
async def admin_tutorials_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "support"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_TUTORIALS_TEXT, reply_markup=tutorial_admin_root_keyboard())
    await callback.answer()
```

- [ ] **Step 6: Wire the router into `app/main.py` and unblock `adm:root`**

In `app/bot/handlers/users.py`, remove `"adm:root"` from `_PLACEHOLDER_CALLBACKS`:

```python
_PLACEHOLDER_CALLBACKS = {
    "menu:buy",
    "menu:renew",
    "menu:myservices",
    "menu:tutorials",
}
```

In `app/main.py`, change:

```python
from app.bot.handlers import fallback, trial, tutorial_admin, users
```
to:
```python
from app.bot.handlers import admin, fallback, trial, tutorial_admin, users
```

and change:
```python
    dp.include_router(users.router)
    dp.include_router(trial.router)
```
to:
```python
    dp.include_router(admin.router)
    dp.include_router(users.router)
    dp.include_router(trial.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_admin_panel_root.py` and the updated `test_start_and_menu.py`.

- [ ] **Step 8: Commit**

```bash
git add app/bot/filters app/bot/keyboards/admin.py app/bot/handlers/admin.py \
        app/bot/handlers/users.py app/main.py \
        tests/functional/test_admin_panel_root.py tests/functional/test_start_and_menu.py
git commit -m "feat: admin panel navigation shell with tier-gated root menu"
```

---

### Task 2: Broadcast

**Files:**
- Create: `app/bot/states/broadcast.py`
- Create: `app/bot/keyboards/broadcast.py`
- Create: `app/bot/handlers/broadcast.py`
- Modify: `app/main.py`
- Modify: `tests/fakes/fake_bot_session.py`
- Test: `tests/functional/test_broadcast.py`

**Interfaces:**
- Consumes: `IsFullAdmin` from `app.bot.filters.admin` (Task 1). `admin_root_menu` from `app.bot.keyboards.admin` (Task 1). `list_bot_user_ids` from `app.services.bot_users` (existing). `has_level` from `app.services.admin_users` (existing).
- Produces: `BroadcastStates` (`content`, `confirm`) — no later task consumes this. Router `broadcast` registered in `app/main.py`.

- [ ] **Step 1: Extend the fake bot session to simulate a blocked recipient**

In `tests/fakes/fake_bot_session.py`, add the import and the blocked-chat check:

```python
from aiogram.exceptions import TelegramForbiddenError
```

and add the `blocked_chat_ids` field:

```python
class FakeBotSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.blocked_chat_ids: set[int] = set()
        self._message_id_counter = itertools.count(1)
```

and in `make_request`, right after `chat_id = data.get("chat_id", 0)`:

```python
        if api_name in ("sendMessage", "sendPhoto", "sendDocument", "sendVideo") and chat_id in self.blocked_chat_ids:
            raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
```

(`.reset()` stays as-is — it only clears `self.calls`; `blocked_chat_ids` is per-test config, not a call log, and a fresh `FakeBotSession` is created per test anyway via the function-scoped `fake_session` fixture.)

- [ ] **Step 2: Write the failing tests**

Create `tests/functional/test_broadcast.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update, seed_bot_user
from tests.fakes.fake_bot_session import FakeBotSession


async def _drain_background_tasks() -> None:
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_non_full_admin_cannot_start_broadcast(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=701, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(701, "adm:broadcast"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("broadcast" in c[1].get("text", "").lower() for c in edited)


@pytest.mark.asyncio
async def test_broadcast_confirm_screen_shows_recipient_count(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    async with async_session_maker() as session:
        await seed_bot_user(session, 711, username="carol")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "hi"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "1 user" in sent[-1][1]["text"]


@pytest.mark.asyncio
async def test_full_admin_broadcasts_text_to_every_bot_user(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    async with async_session_maker() as session:
        await seed_bot_user(session, 712, username="alice")
        await seed_bot_user(session, 713, username="bob")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "Scheduled maintenance tonight."))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:confirm"))
    await _drain_background_tasks()

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    recipients = {c[1]["chat_id"] for c in sent if c[1].get("text") == "Scheduled maintenance tonight."}
    assert recipients == {712, 713}
    summary = next(c for c in sent if "broadcast done" in c[1].get("text", "").lower())
    assert "sent: 2" in summary[1]["text"].lower()


@pytest.mark.asyncio
async def test_broadcast_continues_past_a_blocked_recipient(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    async with async_session_maker() as session:
        await seed_bot_user(session, 714, username="blocked_user")
        await seed_bot_user(session, 715, username="reachable_user")
    fake_session.blocked_chat_ids.add(714)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "hello all"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:confirm"))
    await _drain_background_tasks()

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    reached = {c[1]["chat_id"] for c in sent if c[1].get("text") == "hello all"}
    assert reached == {715}
    summary = next(c for c in sent if "broadcast done" in c[1].get("text", "").lower())
    assert "sent: 1" in summary[1]["text"].lower()
    assert "failed: 1" in summary[1]["text"].lower()


@pytest.mark.asyncio
async def test_broadcast_cancel_returns_to_admin_root(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:cancel"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "admin panel" in edited[-1][1]["text"].lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_broadcast.py`)
Expected: FAIL — `adm:broadcast` has no handler yet.

- [ ] **Step 4: Create the broadcast states and keyboards**

`app/bot/states/broadcast.py`:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BroadcastStates(StatesGroup):
    content = State()
    confirm = State()
```

`app/bot/keyboards/broadcast.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

CANCEL_CB = "adm:broadcast:cancel"
CONFIRM_CB = "adm:broadcast:confirm"


def broadcast_compose_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data=CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Send", callback_data=CONFIRM_CB, style="success")
    builder.button(text="❌ Cancel", callback_data=CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Create the broadcast handler**

`app/bot/handlers/broadcast.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin import admin_root_menu
from app.bot.keyboards.broadcast import broadcast_compose_keyboard, broadcast_confirm_keyboard
from app.bot.states.broadcast import BroadcastStates
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.bot_users import list_bot_user_ids

router = Router(name="broadcast")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

logger = logging.getLogger(__name__)

_SEND_DELAY_SECONDS = 0.05
_COMPOSE_TEXT = "📢 Send the message to broadcast — text, a photo, or a document:"


@router.callback_query(F.data == "adm:broadcast")
async def broadcast_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.content)
    if callback.message is not None:
        await callback.message.edit_text(_COMPOSE_TEXT, reply_markup=broadcast_compose_keyboard())
    await callback.answer()


@router.message(BroadcastStates.content)
async def broadcast_receive_content_msg(message: Message, state: FSMContext) -> None:
    if message.photo:
        content: dict[str, Any] = {"kind": "photo", "file_id": message.photo[-1].file_id, "caption": message.caption or ""}
    elif message.document:
        content = {"kind": "document", "file_id": message.document.file_id, "caption": message.caption or ""}
    elif message.text:
        content = {"kind": "text", "text": message.text}
    else:
        await message.answer("⚠️ Send text, a photo, or a document.", reply_markup=broadcast_compose_keyboard())
        return

    await state.update_data(content=content)
    await state.set_state(BroadcastStates.confirm)

    async with async_session_maker() as session:
        recipient_count = len(await list_bot_user_ids(session))
    await message.answer(
        f"📢 Ready to broadcast to {recipient_count} user(s). Send it?",
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.callback_query(BroadcastStates.confirm, F.data == "adm:broadcast:confirm")
async def broadcast_confirm_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    content = data["content"]
    await state.clear()

    if callback.message is not None:
        await callback.message.edit_text("📤 Broadcast started — you'll get a summary when it's done.")
    await callback.answer()

    asyncio.create_task(_run_broadcast(callback.bot, callback.from_user.id, content))


@router.callback_query(F.data == "adm:broadcast:cancel")
async def broadcast_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        is_sales = await has_level(session, callback.from_user.id, "sales")
        is_full = await has_level(session, callback.from_user.id, "full")
    if callback.message is not None:
        await callback.message.edit_text(
            "🛠 <b>Admin Panel</b>", reply_markup=admin_root_menu(is_sales_admin=is_sales, is_full_admin=is_full)
        )
    await callback.answer()


async def _run_broadcast(bot: Bot, admin_telegram_id: int, content: dict[str, Any]) -> None:
    async with async_session_maker() as session:
        recipient_ids = await list_bot_user_ids(session)

    sent, failed = 0, 0
    for telegram_id in recipient_ids:
        try:
            if content["kind"] == "text":
                await bot.send_message(telegram_id, content["text"])
            elif content["kind"] == "photo":
                await bot.send_photo(telegram_id, content["file_id"], caption=content["caption"] or None)
            else:
                await bot.send_document(telegram_id, content["file_id"], caption=content["caption"] or None)
            sent += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(_SEND_DELAY_SECONDS)

    try:
        await bot.send_message(admin_telegram_id, f"✅ Broadcast done — sent: {sent}, failed: {failed}.")
    except TelegramAPIError:
        logger.exception("Could not deliver broadcast summary to admin telegram_id=%s", admin_telegram_id)
```

- [ ] **Step 6: Wire the router into `app/main.py`**

Change:
```python
from app.bot.handlers import admin, fallback, trial, tutorial_admin, users
```
to:
```python
from app.bot.handlers import admin, broadcast, fallback, trial, tutorial_admin, users
```

Change:
```python
    dp.include_router(admin.router)
    dp.include_router(users.router)
```
to:
```python
    dp.include_router(admin.router)
    dp.include_router(broadcast.router)
    dp.include_router(users.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_broadcast.py`, and no regression elsewhere.

- [ ] **Step 8: Commit**

```bash
git add app/bot/states/broadcast.py app/bot/keyboards/broadcast.py app/bot/handlers/broadcast.py \
        app/main.py tests/fakes/fake_bot_session.py tests/functional/test_broadcast.py
git commit -m "feat: admin broadcast flow with background sender"
```

---

### Task 3: Block/unblock users UI

**Files:**
- Create: `app/bot/states/admin_block.py`
- Create: `app/bot/keyboards/admin_block.py`
- Create: `app/bot/handlers/admin_block.py`
- Modify: `app/services/bot_users.py`
- Modify: `app/main.py`
- Test: `tests/functional/test_admin_block_users.py`

**Interfaces:**
- Consumes: `block_user(session, telegram_id, blocked=True)` from `app.services.bot_users` (existing). `has_level` from `app.services.admin_users` (existing).
- Produces: `list_blocked_users(session) -> list[BotUser]` (new, `app.services.bot_users`) — no later task consumes this, but it belongs on the same service module per CLAUDE.md's "new feature = new router + new service method" convention.

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_admin_block_users.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update, seed_bot_user
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_admin_cannot_access_blocked_list(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "adm:users:blocked:0"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_blocked_list_shows_empty_message_when_none_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:blocked:0"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no blocked users" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_admin_can_block_a_known_user_by_id(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import is_blocked

    async with async_session_maker() as session:
        await seed_bot_user(session, 801, username="target")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:block"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "801"))

    async with async_session_maker() as session:
        assert await is_blocked(session, 801) is True


@pytest.mark.asyncio
async def test_blocking_unknown_telegram_id_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:block"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "424242"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("never interacted" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_non_numeric_block_input_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:block"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "not-a-number"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("numeric" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_admin_can_unblock_from_list(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import block_user, is_blocked

    async with async_session_maker() as session:
        await seed_bot_user(session, 802, username="blocked_target")
        await block_user(session, 802, blocked=True)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:blocked:0"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert any("blocked_target" in b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:unblock:802:0"))

    async with async_session_maker() as session:
        assert await is_blocked(session, 802) is False


@pytest.mark.asyncio
async def test_blocked_list_paginates_at_8_per_page(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import block_user

    async with async_session_maker() as session:
        for i in range(9):
            telegram_id = 900 + i
            await seed_bot_user(session, telegram_id, username=f"user{i}")
            await block_user(session, telegram_id, blocked=True)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:blocked:0"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert sum(1 for b in buttons if b.startswith("✅ Unblock")) == 8
    assert any("next" in b.lower() for b in buttons)

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:blocked:1"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert sum(1 for b in buttons if b.startswith("✅ Unblock")) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_admin_block_users.py`)
Expected: FAIL — none of the `adm:users:blocked:*` / `adm:users:block` / `adm:users:unblock:*` callbacks have a handler yet.

- [ ] **Step 3: Add `list_blocked_users` to the bot_users service**

In `app/services/bot_users.py`, add below `is_blocked`:

```python
async def list_blocked_users(session: AsyncSession) -> list[BotUser]:
    result = await session.execute(select(BotUser).where(BotUser.is_blocked.is_(True)).order_by(BotUser.id))
    return list(result.scalars().all())
```

- [ ] **Step 4: Create the block-flow state and keyboards**

`app/bot/states/admin_block.py`:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BlockUserStates(StatesGroup):
    telegram_id = State()
```

`app/bot/keyboards/admin_block.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.bot_user import BotUser

PAGE_SIZE = 8


def blocked_users_keyboard(page_items: list[BotUser], *, page: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in page_items:
        label = f"@{user.username}" if user.username else str(user.telegram_id)
        builder.button(text=f"✅ Unblock {label}", callback_data=f"adm:users:unblock:{user.telegram_id}:{page}")
    sizes = [1] * len(page_items)

    nav_count = 0
    if page > 0:
        builder.button(text="◀️ Prev", callback_data=f"adm:users:blocked:{page - 1}")
        nav_count += 1
    if (page + 1) * PAGE_SIZE < total:
        builder.button(text="Next ▶️", callback_data=f"adm:users:blocked:{page + 1}")
        nav_count += 1
    if nav_count:
        sizes.append(nav_count)

    builder.button(text="🚫 Block a User", callback_data="adm:users:block")
    builder.button(text="⬅️ Back to Users", callback_data="adm:users")
    sizes += [1, 1]
    builder.adjust(*sizes)
    return builder.as_markup()


def block_user_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:users:blocked:0")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Create the block/unblock handler**

`app/bot/handlers/admin_block.py`:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.bot.keyboards.admin_block import PAGE_SIZE, block_user_prompt_keyboard, blocked_users_keyboard
from app.bot.states.admin_block import BlockUserStates
from app.db.models.bot_user import BotUser
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.bot_users import block_user, list_blocked_users

router = Router(name="admin_block")

_BLOCKED_LIST_TEXT = "🚫 <b>Blocked Users</b>"
_BLOCK_PROMPT_TEXT = "Send the numeric Telegram ID to block:"
_NOT_A_NUMBER_TEXT = "⚠️ Send a numeric Telegram ID."
_NEVER_SEEN_TEXT = "⚠️ That Telegram ID has never interacted with the bot — nothing to block."


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


async def _render_page(page: int) -> tuple[str, InlineKeyboardMarkup]:
    async with async_session_maker() as session:
        blocked = await list_blocked_users(session)
    total = len(blocked)
    start = page * PAGE_SIZE
    page_items = blocked[start : start + PAGE_SIZE]
    text = _BLOCKED_LIST_TEXT if page_items else f"{_BLOCKED_LIST_TEXT}\n\nNo blocked users."
    return text, blocked_users_keyboard(page_items, page=page, total=total)


@router.callback_query(F.data.startswith("adm:users:blocked:"))
async def admin_blocked_list_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    page = int(callback.data.split(":")[-1])
    text, keyboard = await _render_page(page)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:users:unblock:"))
async def admin_unblock_cb(callback: CallbackQuery) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, _, telegram_id_str, page_str = callback.data.split(":")
    async with async_session_maker() as session:
        await block_user(session, int(telegram_id_str), blocked=False)
    text, keyboard = await _render_page(int(page_str))
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("✅ Unblocked.")


@router.callback_query(F.data == "adm:users:block")
async def admin_block_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BlockUserStates.telegram_id)
    if callback.message is not None:
        await callback.message.edit_text(_BLOCK_PROMPT_TEXT, reply_markup=block_user_prompt_keyboard())
    await callback.answer()


@router.message(BlockUserStates.telegram_id)
async def admin_block_receive_id(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(_NOT_A_NUMBER_TEXT, reply_markup=block_user_prompt_keyboard())
        return
    telegram_id = int(raw)

    async with async_session_maker() as session:
        row = (await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))).scalar_one_or_none()
        if row is None:
            await message.answer(_NEVER_SEEN_TEXT, reply_markup=block_user_prompt_keyboard())
            return
        await block_user(session, telegram_id, blocked=True)

    await state.clear()
    text, keyboard = await _render_page(0)
    await message.answer(f"✅ Blocked {telegram_id}.\n\n{text}", reply_markup=keyboard)
```

- [ ] **Step 6: Wire the router into `app/main.py`**

Change:
```python
from app.bot.handlers import admin, broadcast, fallback, trial, tutorial_admin, users
```
to:
```python
from app.bot.handlers import admin, admin_block, broadcast, fallback, trial, tutorial_admin, users
```

Change:
```python
    dp.include_router(admin.router)
    dp.include_router(broadcast.router)
```
to:
```python
    dp.include_router(admin.router)
    dp.include_router(admin_block.router)
    dp.include_router(broadcast.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_admin_block_users.py`, and no regression elsewhere.

- [ ] **Step 8: Commit**

```bash
git add app/services/bot_users.py app/bot/states/admin_block.py app/bot/keyboards/admin_block.py \
        app/bot/handlers/admin_block.py app/main.py tests/functional/test_admin_block_users.py
git commit -m "feat: admin block/unblock UI with paginated blocked-user list"
```

---

### Task 4: Admin renew-by-username

**Files:**
- Modify: `app/services/ibsng/client.py`
- Modify: `app/services/vpn_users.py`
- Modify: `tests/functional/test_ibsng_client.py`
- Modify: `tests/functional/test_vpn_users.py`
- Create: `app/bot/states/admin_renew.py`
- Create: `app/bot/keyboards/admin_renew.py`
- Create: `app/bot/handlers/admin_renew.py`
- Modify: `app/main.py`
- Test: `tests/functional/test_admin_renew.py`

**Interfaces:**
- Produces: `IBSngClient.renew_user(*, username: str) -> None` (raises `IBSngUserNotFoundError` if the username doesn't exist). `vpn_users.renew_and_change_group(session, client, *, username: str, new_group_name: str, new_plan_id: int | None, new_data_cap_mb: int) -> None`.
- Consumes: `catalog.list_plans` / `catalog.get_plan` / `catalog.format_price_usd` (existing). `IBSngError`, `IBSngUserNotFoundError` from `app.services.ibsng.exceptions` (existing).

- [ ] **Step 1: Write the failing IBSngClient tests**

Append to `tests/functional/test_ibsng_client.py` (read the existing file first to match its fixture usage — it already has `ibsng_server`/session-scoped setup; add these as new test functions using the same `IBSngClient` async-context-manager pattern the rest of that file uses):

```python
@pytest.mark.asyncio
async def test_renew_user_is_idempotent() -> None:
    from app.services.ibsng.client import IBSngClient

    async with IBSngClient() as client:
        await client.create_user(username="renew-target", password="abc123", group_name="Trial-Iran", credit=1024)
        await client.renew_user(username="renew-target")
        await client.renew_user(username="renew-target")  # second call must not raise


@pytest.mark.asyncio
async def test_renew_user_raises_not_found_for_unknown_username() -> None:
    from app.services.ibsng.client import IBSngClient
    from app.services.ibsng.exceptions import IBSngUserNotFoundError

    async with IBSngClient() as client:
        with pytest.raises(IBSngUserNotFoundError):
            await client.renew_user(username="does-not-exist")
```

- [ ] **Step 2: Write the failing vpn_users tests**

Append to `tests/functional/test_vpn_users.py` (match its existing fixture/import style — it already uses `seeded_catalog`, `IBSngClient`, `create_vpn_user`):

```python
@pytest.mark.asyncio
async def test_renew_and_change_group_updates_tracked_vpn_user(seeded_catalog: dict) -> None:
    from sqlalchemy import select

    from app.db.models.vpn_user import VPNUser
    from app.db.session import async_session_maker
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials, renew_and_change_group

    scroll_plans = [p for p in seeded_catalog["plans"] if p["category"] == "scroll"]
    old_plan, new_plan = scroll_plans[0], scroll_plans[1]
    username, password = generate_vpn_credentials()

    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client, telegram_id=12345, username=username, password=password,
            group_name=old_plan["group_name"], data_cap_mb=old_plan["data_cap_mb"], plan_id=old_plan["id"],
        )

    async with async_session_maker() as session, IBSngClient() as client:
        await renew_and_change_group(
            session, client, username=username, new_group_name=new_plan["group_name"],
            new_plan_id=new_plan["id"], new_data_cap_mb=new_plan["data_cap_mb"],
        )

    async with async_session_maker() as session:
        refreshed = (await session.execute(select(VPNUser).where(VPNUser.id == vpn_user.id))).scalar_one()
    assert refreshed.ibsng_group == new_plan["group_name"]
    assert refreshed.plan_id == new_plan["id"]
    assert refreshed.data_cap_mb == new_plan["data_cap_mb"]


@pytest.mark.asyncio
async def test_renew_and_change_group_is_ibsng_only_when_no_local_row(seeded_catalog: dict) -> None:
    from sqlalchemy import select

    from app.db.models.vpn_user import VPNUser
    from app.db.session import async_session_maker
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import renew_and_change_group

    scroll_plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll")

    async with IBSngClient() as client:
        await client.create_user(username="ibsng-only-user", password="abc123", group_name="Trial-Iran", credit=512)

    async with async_session_maker() as session, IBSngClient() as client:
        await renew_and_change_group(
            session, client, username="ibsng-only-user", new_group_name=scroll_plan["group_name"],
            new_plan_id=scroll_plan["id"], new_data_cap_mb=scroll_plan["data_cap_mb"],
        )

    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == "ibsng-only-user"))).scalars().all()
    assert list(rows) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `make test` (target the two modified files)
Expected: FAIL — `IBSngClient` has no `renew_user`, `vpn_users` has no `renew_and_change_group`.

- [ ] **Step 4: Add `renew_user` to `IBSngClient`**

In `app/services/ibsng/client.py`, add below `change_user_group`:

```python
    async def renew_user(self, *, username: str) -> None:
        """Mirrors IBSng's admin-panel 'reset first login' action: clears
        the first_login attribute so validity restarts from the account's
        next connection. Idempotent - deleting an already-unset attribute
        is a no-op, safe to retry."""
        user_id = await self._require_user_id(username)
        await self._call("user.updateUserAttrs", user_id=user_id, attrs={}, to_del_attrs=["first_login"])
```

- [ ] **Step 5: Add `renew_and_change_group` to `vpn_users.py`**

In `app/services/vpn_users.py`, add at the end of the file:

```python
async def renew_and_change_group(
    session: AsyncSession,
    client: IBSngClient,
    *,
    username: str,
    new_group_name: str,
    new_plan_id: int | None,
    new_data_cap_mb: int,
) -> None:
    """Renews (resets validity) AND moves to a (possibly different)
    group/plan in one IBSng-side action. Updates the locally-tracked
    VPNUser row if this username is tracked (was created through the
    bot) - otherwise this is IBSng-only, no local row to update."""
    await client.renew_user(username=username)
    await client.change_user_group(username=username, group_name=new_group_name)
    vpn_user = (
        await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
    ).scalar_one_or_none()
    if vpn_user is not None:
        vpn_user.ibsng_group = new_group_name
        vpn_user.plan_id = new_plan_id
        vpn_user.data_cap_mb = new_data_cap_mb
        vpn_user.expiry_reminder_sent_at = None
        vpn_user.low_quota_reminder_sent_at = None
        await session.commit()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `make test`
Expected: PASS for the service-level tests. The UI flow tests come next.

- [ ] **Step 7: Write the failing admin-renew flow tests**

Create `tests/functional/test_admin_renew.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_admin_cannot_start_renew_flow(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "adm:users:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_admin_renews_unknown_ibsng_username_shows_not_found(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    scroll_plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ghost-user"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renew:plan:{scroll_plan['id']}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_admin_renews_bot_created_account_updates_row_and_notifies_user(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    scroll_plans = [p for p in seeded_catalog["plans"] if p["category"] == "scroll"]
    old_plan, new_plan = scroll_plans[0], scroll_plans[1]
    username, password = generate_vpn_credentials()
    customer_telegram_id = 5551234

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=customer_telegram_id, username=username, password=password,
            group_name=old_plan["group_name"], data_cap_mb=old_plan["data_cap_mb"], plan_id=old_plan["id"],
        )

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, username))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renew:plan:{new_plan['id']}"))

    async with async_session_maker() as session:
        refreshed = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))).scalar_one()
    assert refreshed.plan_id == new_plan["id"]
    assert refreshed.ibsng_group == new_plan["group_name"]

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any(c[1]["chat_id"] == customer_telegram_id for c in sent)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "renewed" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_admin_renews_ibsng_only_username_not_tracked_locally(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.ibsng.client import IBSngClient

    scroll_plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll")

    async with IBSngClient() as client:
        await client.create_user(username="ibsng-only-admin-test", password="abc123", group_name="Trial-Iran", credit=512)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ibsng-only-admin-test"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renew:plan:{scroll_plan['id']}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "wasn't created through the bot" in edited[-1][1]["text"].lower()
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_admin_renew.py`)
Expected: FAIL — `adm:users:renew` has no handler yet.

- [ ] **Step 9: Create the renew-flow state and keyboards**

`app/bot/states/admin_renew.py`:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminRenewStates(StatesGroup):
    username = State()
    plan = State()
```

`app/bot/keyboards/admin_renew.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.services.catalog import format_price_usd


def admin_renew_username_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:users")
    builder.adjust(1)
    return builder.as_markup()


def admin_renew_plan_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan.name} — {format_price_usd(plan.price_usd)}",
            callback_data=f"adm:users:renew:plan:{plan.id}",
        )
    builder.button(text="❌ Cancel", callback_data="adm:users")
    builder.adjust(1)
    return builder.as_markup()


def admin_renew_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Users", callback_data="adm:users")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 10: Create the renew-flow handler**

`app/bot/handlers/admin_renew.py`:

```python
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards.admin_renew import (
    admin_renew_plan_keyboard,
    admin_renew_result_keyboard,
    admin_renew_username_prompt_keyboard,
)
from app.bot.states.admin_renew import AdminRenewStates
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.catalog import get_plan, list_plans
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserNotFoundError
from app.services.vpn_users import renew_and_change_group

router = Router(name="admin_renew")

logger = logging.getLogger(__name__)

_USERNAME_PROMPT_TEXT = "Send the IBSng username to renew:"
_EMPTY_USERNAME_TEXT = "⚠️ Send a non-empty username."
_PLAN_PROMPT_TEXT = "Pick the plan/group to renew into:"
_PLAN_GONE_TEXT = "⚠️ That plan no longer exists. Start over."


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


@router.callback_query(F.data == "adm:users:renew")
async def admin_renew_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminRenewStates.username)
    if callback.message is not None:
        await callback.message.edit_text(_USERNAME_PROMPT_TEXT, reply_markup=admin_renew_username_prompt_keyboard())
    await callback.answer()


@router.message(AdminRenewStates.username)
async def admin_renew_receive_username(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    username = (message.text or "").strip()
    if not username:
        await message.answer(_EMPTY_USERNAME_TEXT, reply_markup=admin_renew_username_prompt_keyboard())
        return
    await state.update_data(username=username)
    await state.set_state(AdminRenewStates.plan)
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    await message.answer(_PLAN_PROMPT_TEXT, reply_markup=admin_renew_plan_keyboard(plans))


@router.callback_query(AdminRenewStates.plan, F.data.startswith("adm:users:renew:plan:"))
async def admin_renew_execute_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    plan_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    username = data["username"]
    await state.clear()

    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=admin_renew_result_keyboard())
        await callback.answer()
        return

    try:
        async with async_session_maker() as session, IBSngClient() as client:
            await renew_and_change_group(
                session, client, username=username, new_group_name=plan.group_name,
                new_plan_id=plan.id, new_data_cap_mb=plan.data_cap_mb,
            )
    except IBSngUserNotFoundError:
        if callback.message is not None:
            await callback.message.edit_text(
                f"⚠️ IBSng user {username!r} not found.", reply_markup=admin_renew_result_keyboard()
            )
        await callback.answer()
        return
    except IBSngError as exc:
        if callback.message is not None:
            await callback.message.edit_text(f"⚠️ {exc}", reply_markup=admin_renew_result_keyboard())
        await callback.answer()
        return

    async with async_session_maker() as session:
        vpn_user = (
            await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
        ).scalar_one_or_none()

    result_text = f"✅ Renewed {username!r} and moved to {plan.name}."
    if vpn_user is None:
        result_text += "\n\n(No local account record — this username wasn't created through the bot.)"
    else:
        try:
            await callback.bot.send_message(
                vpn_user.telegram_id,
                f"✅ Your Homeland VPN service was renewed by support — now on {plan.name}.",
            )
        except TelegramAPIError:
            logger.exception("Could not notify telegram_id=%s about their renewal", vpn_user.telegram_id)

    if callback.message is not None:
        await callback.message.edit_text(result_text, reply_markup=admin_renew_result_keyboard())
    await callback.answer()
```

- [ ] **Step 11: Wire the router into `app/main.py`**

Change:
```python
from app.bot.handlers import admin, admin_block, broadcast, fallback, trial, tutorial_admin, users
```
to:
```python
from app.bot.handlers import admin, admin_block, admin_renew, broadcast, fallback, trial, tutorial_admin, users
```

Change:
```python
    dp.include_router(admin.router)
    dp.include_router(admin_block.router)
    dp.include_router(broadcast.router)
```
to:
```python
    dp.include_router(admin.router)
    dp.include_router(admin_block.router)
    dp.include_router(admin_renew.router)
    dp.include_router(broadcast.router)
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_admin_renew.py`, the extended `test_ibsng_client.py`/`test_vpn_users.py`, and no regression elsewhere.

- [ ] **Step 13: Commit**

```bash
git add app/services/ibsng/client.py app/services/vpn_users.py \
        tests/functional/test_ibsng_client.py tests/functional/test_vpn_users.py \
        app/bot/states/admin_renew.py app/bot/keyboards/admin_renew.py app/bot/handlers/admin_renew.py \
        app/main.py tests/functional/test_admin_renew.py
git commit -m "feat: admin renew-by-username, filling Homeland's only-way-to-extend-a-service gap"
```

---

### Task 5: DiscountCode model + migration + service

**Files:**
- Create: `app/db/models/discount_code.py`
- Modify: `app/db/models/__init__.py`
- Create: `alembic/versions/0006_discount_codes.py`
- Create: `app/services/discounts.py`
- Test: `tests/functional/test_discounts.py`

**Interfaces:**
- Produces: `DiscountCode` model. `normalize_discount_code`, `discount_price`, `create_discount_code`, `update_discount_code`, `set_discount_active`, `delete_discount_code`, `get_discount_code`, `get_discount_code_by_name`, `list_discount_codes`, `validate_discount_code`, `find_best_auto_discount`, `DiscountCodeInvalidError` (`app.services.discounts`) — Task 6's UI flow consumes all of these except `discount_price`/`validate_discount_code`/`find_best_auto_discount` (those three are for the future Buy flow, per spec §1/§7).
- Consumes: nothing new — `app.db.base.Base` only.

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_discounts.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.session import async_session_maker
from app.services.discounts import (
    DiscountCodeInvalidError,
    create_discount_code,
    delete_discount_code,
    discount_price,
    find_best_auto_discount,
    get_discount_code,
    normalize_discount_code,
    set_discount_active,
    update_discount_code,
    validate_discount_code,
)


def _plan_id(seeded_catalog: dict, category: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category)


@pytest.mark.asyncio
async def test_create_discount_code_normalizes_code_to_uppercase() -> None:
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="  welcome10  ", percent=Decimal("10"), usage_limit=None, plan_ids=None)
    assert discount.code == "WELCOME10"


def test_normalize_discount_code_strips_and_uppercases() -> None:
    assert normalize_discount_code("  hello ") == "HELLO"


def test_discount_price_applies_percent_and_rounds() -> None:
    assert discount_price(Decimal("19.99"), Decimal("10")) == Decimal("17.99")


@pytest.mark.asyncio
async def test_update_discount_code_changes_fields_but_not_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="ORIGINAL", percent=Decimal("10"), usage_limit=5, plan_ids=None)
        updated = await update_discount_code(
            session, discount.id, percent=Decimal("20"), usage_limit=None, plan_ids=[scroll_id], is_public=False
        )
    assert updated.code == "ORIGINAL"
    assert updated.percent == Decimal("20")
    assert updated.usage_limit is None
    assert updated.plan_ids == str(scroll_id)
    assert updated.is_public is False


@pytest.mark.asyncio
async def test_set_discount_active_toggles() -> None:
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="TOGGLE", percent=Decimal("5"), usage_limit=None, plan_ids=None)
        toggled = await set_discount_active(session, discount.id, False)
    assert toggled.is_active is False


@pytest.mark.asyncio
async def test_delete_discount_code_removes_row() -> None:
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="DELME", percent=Decimal("5"), usage_limit=None, plan_ids=None)
        deleted = await delete_discount_code(session, discount.id)
        missing = await get_discount_code(session, discount.id)
    assert deleted is True
    assert missing is None


@pytest.mark.asyncio
async def test_validate_discount_code_raises_for_unknown_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="NOPE", plan_id=scroll_id)


@pytest.mark.asyncio
async def test_validate_discount_code_raises_when_inactive(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="INACTIVE1", percent=Decimal("10"), usage_limit=None, plan_ids=None)
        await set_discount_active(session, discount.id, False)
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="INACTIVE1", plan_id=scroll_id)


@pytest.mark.asyncio
async def test_validate_discount_code_raises_when_exhausted(seeded_catalog: dict) -> None:
    from app.db.models.discount_code import DiscountCode

    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="EXHAUSTED", percent=Decimal("10"), usage_limit=1, plan_ids=None)
        discount.used_count = 1
        await session.commit()
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="EXHAUSTED", plan_id=scroll_id)


@pytest.mark.asyncio
async def test_validate_discount_code_raises_when_plan_not_scoped(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    stream_id = _plan_id(seeded_catalog, "stream")
    async with async_session_maker() as session:
        await create_discount_code(session, code="SCROLLONLY", percent=Decimal("10"), usage_limit=None, plan_ids=[scroll_id])
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="SCROLLONLY", plan_id=stream_id)


@pytest.mark.asyncio
async def test_validate_discount_code_succeeds_for_valid_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        await create_discount_code(session, code="VALID10", percent=Decimal("10"), usage_limit=None, plan_ids=None)
        discount = await validate_discount_code(session, code="valid10", plan_id=scroll_id)
    assert discount.code == "VALID10"


@pytest.mark.asyncio
async def test_find_best_auto_discount_picks_highest_percent_public_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        await create_discount_code(session, code="LOW", percent=Decimal("5"), usage_limit=None, plan_ids=None, is_public=True)
        await create_discount_code(session, code="HIGH", percent=Decimal("25"), usage_limit=None, plan_ids=None, is_public=True)
        best = await find_best_auto_discount(session, scroll_id)
    assert best.code == "HIGH"


@pytest.mark.asyncio
async def test_find_best_auto_discount_ignores_private_codes(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        await create_discount_code(session, code="PUBLIC5", percent=Decimal("5"), usage_limit=None, plan_ids=None, is_public=True)
        await create_discount_code(session, code="PRIVATE99", percent=Decimal("99"), usage_limit=None, plan_ids=None, is_public=False)
        best = await find_best_auto_discount(session, scroll_id)
    assert best.code == "PUBLIC5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_discounts.py`)
Expected: FAIL — `app.services.discounts` and `app.db.models.discount_code` don't exist yet.

- [ ] **Step 3: Create the DiscountCode model**

`app/db/models/discount_code.py`:

```python
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiscountCode(Base):
    """A percent-off code, scoped to zero or more Plans via a comma-joined
    `plan_ids` string (NULL = applies to every plan) - Homeland's flat
    catalog has no `categories` dimension like AloBot's DiscountCode, so
    this is the one field that differs from the ported original.
    `used_count` stays at its default of 0 until the Buy/payments plan
    wires up the increment call (see the admin panel spec §1/§7) -
    nothing in this codebase increments it yet."""

    __tablename__ = "discount_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    plan_ids: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

In `app/db/models/__init__.py`, change:

```python
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser
from app.db.models.group import Group
from app.db.models.openvpn_profile import OpenVpnProfile
from app.db.models.plan import Plan
from app.db.models.tutorial_guide import TutorialGuide
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser

__all__ = [
    "AdminUser", "AppConfig", "BotUser", "Group", "OpenVpnProfile", "Plan",
    "TutorialGuide", "TutorialPlatform", "TutorialProtocol", "VPNUser",
]
```
to:
```python
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser
from app.db.models.discount_code import DiscountCode
from app.db.models.group import Group
from app.db.models.openvpn_profile import OpenVpnProfile
from app.db.models.plan import Plan
from app.db.models.tutorial_guide import TutorialGuide
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser

__all__ = [
    "AdminUser", "AppConfig", "BotUser", "DiscountCode", "Group", "OpenVpnProfile", "Plan",
    "TutorialGuide", "TutorialPlatform", "TutorialProtocol", "VPNUser",
]
```

- [ ] **Step 4: Create the migration**

`alembic/versions/0006_discount_codes.py`:

```python
"""discount_codes table

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discount_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plan_ids", sa.String(256), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_discount_codes_code", "discount_codes", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_discount_codes_code", table_name="discount_codes")
    op.drop_table("discount_codes")
```

- [ ] **Step 5: Create the discounts service**

`app/services/discounts.py`:

```python
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discount_code import DiscountCode


class DiscountCodeInvalidError(Exception):
    """Raised by validate_discount_code with a human-readable reason -
    not-found / inactive / exhausted / not scoped to this plan."""


def normalize_discount_code(code: str) -> str:
    return code.strip().upper()


def discount_price(original: Decimal, percent: Decimal) -> Decimal:
    discounted = original * (Decimal("100") - percent) / Decimal("100")
    return discounted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _plan_ids_str(plan_ids: list[int] | None) -> str | None:
    return ",".join(str(p) for p in plan_ids) if plan_ids else None


async def create_discount_code(
    session: AsyncSession,
    *,
    code: str,
    percent: Decimal,
    usage_limit: int | None,
    plan_ids: list[int] | None,
    is_public: bool = True,
) -> DiscountCode:
    discount = DiscountCode(
        code=normalize_discount_code(code),
        percent=percent,
        usage_limit=usage_limit,
        plan_ids=_plan_ids_str(plan_ids),
        is_public=is_public,
    )
    session.add(discount)
    await session.commit()
    await session.refresh(discount)
    return discount


async def update_discount_code(
    session: AsyncSession,
    discount_code_id: int,
    *,
    percent: Decimal,
    usage_limit: int | None,
    plan_ids: list[int] | None,
    is_public: bool,
) -> DiscountCode | None:
    """The code text itself is never editable after creation - matching
    AloBot, and avoiding the ambiguity of what happens to in-flight uses
    of the old code text."""
    discount = await session.get(DiscountCode, discount_code_id)
    if discount is None:
        return None
    discount.percent = percent
    discount.usage_limit = usage_limit
    discount.plan_ids = _plan_ids_str(plan_ids)
    discount.is_public = is_public
    await session.commit()
    await session.refresh(discount)
    return discount


async def set_discount_active(session: AsyncSession, discount_code_id: int, active: bool) -> DiscountCode | None:
    discount = await session.get(DiscountCode, discount_code_id)
    if discount is None:
        return None
    discount.is_active = active
    await session.commit()
    await session.refresh(discount)
    return discount


async def delete_discount_code(session: AsyncSession, discount_code_id: int) -> bool:
    discount = await session.get(DiscountCode, discount_code_id)
    if discount is None:
        return False
    await session.delete(discount)
    await session.commit()
    return True


async def get_discount_code(session: AsyncSession, discount_code_id: int) -> DiscountCode | None:
    return await session.get(DiscountCode, discount_code_id)


async def get_discount_code_by_name(session: AsyncSession, code: str) -> DiscountCode | None:
    result = await session.execute(select(DiscountCode).where(DiscountCode.code == normalize_discount_code(code)))
    return result.scalar_one_or_none()


async def list_discount_codes(session: AsyncSession) -> list[DiscountCode]:
    result = await session.execute(select(DiscountCode).order_by(DiscountCode.id))
    return list(result.scalars().all())


def _is_within_usage_limit(discount: DiscountCode) -> bool:
    return discount.usage_limit is None or discount.used_count < discount.usage_limit


def _applies_to_plan(discount: DiscountCode, plan_id: int) -> bool:
    return discount.plan_ids is None or str(plan_id) in discount.plan_ids.split(",")


async def validate_discount_code(session: AsyncSession, *, code: str, plan_id: int) -> DiscountCode:
    discount = await get_discount_code_by_name(session, code)
    if discount is None:
        raise DiscountCodeInvalidError("Discount code not found.")
    if not discount.is_active:
        raise DiscountCodeInvalidError("This discount code is no longer active.")
    if not _is_within_usage_limit(discount):
        raise DiscountCodeInvalidError("This discount code has reached its usage limit.")
    if not _applies_to_plan(discount, plan_id):
        raise DiscountCodeInvalidError("This discount code doesn't apply to the selected plan.")
    return discount


async def find_best_auto_discount(session: AsyncSession, plan_id: int) -> DiscountCode | None:
    """Highest-percent active, non-exhausted, PUBLIC code scoped to
    plan_id. Built now so the future Buy flow can call it; unused until
    then - see the admin panel spec §1/§7."""
    candidates = [
        d
        for d in await list_discount_codes(session)
        if d.is_active and d.is_public and _is_within_usage_limit(d) and _applies_to_plan(d, plan_id)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.percent)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_discounts.py`, and no regression elsewhere (the migration adds a new table; `_clean_database` in `tests/conftest.py` TRUNCATEs it automatically via `Base.metadata.sorted_tables` since `app/db/models/__init__.py` now imports it — no conftest changes needed).

- [ ] **Step 7: Commit**

```bash
git add app/db/models/discount_code.py app/db/models/__init__.py \
        alembic/versions/0006_discount_codes.py app/services/discounts.py tests/functional/test_discounts.py
git commit -m "feat: DiscountCode model, schema, and validation service"
```

---

### Task 6: Discount code admin CRUD flow

**Files:**
- Create: `app/bot/states/admin_discounts.py`
- Create: `app/bot/keyboards/admin_discounts.py`
- Create: `app/bot/handlers/admin_discounts.py`
- Modify: `app/main.py`
- Test: `tests/functional/test_admin_discounts.py`

**Interfaces:**
- Consumes: `IsSalesAdmin` from `app.bot.filters.admin` (Task 1). `create_discount_code`, `update_discount_code`, `set_discount_active`, `delete_discount_code`, `get_discount_code`, `get_discount_code_by_name`, `list_discount_codes`, `normalize_discount_code` from `app.services.discounts` (Task 5). `list_plans`, `get_plan` from `app.services.catalog` (existing).
- Produces: `DiscountCodeStates` (`name`, `percent`, `usage_limit`, `plans`, `visibility`) — no later task consumes this.

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_admin_discounts.py`:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


def _plan_id(seeded_catalog: dict, category: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category)


@pytest.mark.asyncio
async def test_non_sales_admin_cannot_open_discounts(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=511, level="support"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(511, "adm:discounts"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("discount codes" in c[1].get("text", "").lower() for c in edited)


@pytest.mark.asyncio
async def test_create_discount_code_full_wizard(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.db.models.discount_code import DiscountCode

    scroll_id = _plan_id(seeded_catalog, "scroll")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:new"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "welcome10"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "10"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:wizard:plan:{scroll_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:plansdone"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:public"))

    async with async_session_maker() as session:
        discount = (await session.execute(select(DiscountCode).where(DiscountCode.code == "WELCOME10"))).scalar_one()
    assert discount.percent == Decimal("10")
    assert discount.usage_limit is None
    assert discount.plan_ids == str(scroll_id)
    assert discount.is_public is True

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "WELCOME10" in edited[-1][1]["text"]


@pytest.mark.asyncio
async def test_duplicate_code_name_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.discounts import create_discount_code

    async with async_session_maker() as session:
        await create_discount_code(session, code="DUPE", percent=Decimal("5"), usage_limit=None, plan_ids=None)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:new"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "dupe"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("already exists" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_wizard_requires_at_least_one_plan(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:new"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "nonelimit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "15"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:plansdone"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert any("select at least one plan" in c[1].get("text", "").lower() for c in answered)


@pytest.mark.asyncio
async def test_toggle_active_flips_status(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.discounts import create_discount_code, get_discount_code

    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="TOGGLE1", percent=Decimal("20"), usage_limit=None, plan_ids=[scroll_id])

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:toggle:{discount.id}"))

    async with async_session_maker() as session:
        refreshed = await get_discount_code(session, discount.id)
    assert refreshed.is_active is False


@pytest.mark.asyncio
async def test_delete_requires_confirmation(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.discounts import create_discount_code, get_discount_code

    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="DELME", percent=Decimal("5"), usage_limit=None, plan_ids=None)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:delete:{discount.id}"))
    async with async_session_maker() as session:
        assert await get_discount_code(session, discount.id) is not None

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:delete:{discount.id}:confirm"))
    async with async_session_maker() as session:
        assert await get_discount_code(session, discount.id) is None


@pytest.mark.asyncio
async def test_edit_skips_name_step_and_preserves_code(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.discounts import create_discount_code, get_discount_code

    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="EDITME", percent=Decimal("10"), usage_limit=None, plan_ids=[scroll_id])

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:edit:{discount.id}"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "25"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:plansdone"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:private"))

    async with async_session_maker() as session:
        refreshed = await get_discount_code(session, discount.id)
    assert refreshed.code == "EDITME"
    assert refreshed.percent == Decimal("25")
    assert refreshed.is_public is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_admin_discounts.py`)
Expected: FAIL — none of the `adm:discounts*` callbacks have a handler yet.

- [ ] **Step 3: Create the discount-wizard state**

`app/bot/states/admin_discounts.py`:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class DiscountCodeStates(StatesGroup):
    name = State()
    percent = State()
    usage_limit = State()
    plans = State()
    visibility = State()
```

- [ ] **Step 4: Create the discount keyboards**

`app/bot/keyboards/admin_discounts.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.discount_code import DiscountCode
from app.db.models.plan import Plan

WIZARD_CANCEL_CB = "adm:discounts"


def discount_list_keyboard(discounts: list[DiscountCode]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in discounts:
        marker = "✅" if d.is_active else "⛔️"
        builder.button(text=f"{marker} {d.code} (-{d.percent}%)", callback_data=f"adm:discounts:view:{d.id}")
    builder.button(text="➕ New Discount Code", callback_data="adm:discounts:new")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()


def discount_detail_keyboard(discount: DiscountCode) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit", callback_data=f"adm:discounts:edit:{discount.id}")
    toggle_label = "⛔️ Deactivate" if discount.is_active else "✅ Activate"
    builder.button(text=toggle_label, callback_data=f"adm:discounts:toggle:{discount.id}")
    builder.button(text="🗑 Delete", callback_data=f"adm:discounts:delete:{discount.id}")
    builder.button(text="⬅️ Back to List", callback_data="adm:discounts")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def discount_delete_confirm_keyboard(discount_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Yes, delete", callback_data=f"adm:discounts:delete:{discount_id}:confirm")
    builder.button(text="❌ Cancel", callback_data=f"adm:discounts:view:{discount_id}")
    builder.adjust(1)
    return builder.as_markup()


def wizard_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()


def wizard_usage_limit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Unlimited", callback_data="adm:discounts:wizard:unlimited")
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()


def wizard_plans_keyboard(plans: list[Plan], selected_ids: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    all_selected = len(selected_ids) == len(plans)
    for plan in plans:
        mark = "☑️" if plan.id in selected_ids else "▫️"
        builder.button(text=f"{mark} {plan.name}", callback_data=f"adm:discounts:wizard:plan:{plan.id}")
    builder.button(
        text="◻️ Deselect All" if all_selected else "🔘 Select All",
        callback_data="adm:discounts:wizard:allplans",
    )
    builder.button(text="✅ Done", callback_data="adm:discounts:wizard:plansdone")
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(*([1] * len(plans)), 1, 1, 1)
    return builder.as_markup()


def wizard_visibility_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🌍 Public", callback_data="adm:discounts:wizard:public")
    builder.button(text="🔒 Private", callback_data="adm:discounts:wizard:private")
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(2, 1)
    return builder.as_markup()
```

- [ ] **Step 5: Create the discount admin handler**

`app/bot/handlers/admin_discounts.py`:

```python
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsSalesAdmin
from app.bot.keyboards.admin_discounts import (
    discount_delete_confirm_keyboard,
    discount_detail_keyboard,
    discount_list_keyboard,
    wizard_cancel_keyboard,
    wizard_plans_keyboard,
    wizard_usage_limit_keyboard,
    wizard_visibility_keyboard,
)
from app.bot.states.admin_discounts import DiscountCodeStates
from app.db.models.discount_code import DiscountCode
from app.db.session import async_session_maker
from app.services.catalog import get_plan, list_plans
from app.services.discounts import (
    create_discount_code,
    delete_discount_code,
    get_discount_code,
    get_discount_code_by_name,
    list_discount_codes,
    normalize_discount_code,
    set_discount_active,
    update_discount_code,
)

router = Router(name="admin_discounts")
router.message.filter(IsSalesAdmin())
router.callback_query.filter(IsSalesAdmin())

_LIST_TEXT = "🏷 <b>Discount Codes</b>"
_NAME_PROMPT_TEXT = "Type the new discount code (letters/numbers, will be upper-cased):"
_DUPLICATE_CODE_TEXT = "⚠️ That code already exists. Type a different one:"
_PERCENT_PROMPT_TEXT = "Type the discount percent (0–100):"
_INVALID_PERCENT_TEXT = "⚠️ Send a number greater than 0 and up to 100."
_USAGE_LIMIT_PROMPT_TEXT = "Type a usage limit, or tap Unlimited:"
_INVALID_USAGE_LIMIT_TEXT = "⚠️ Send a positive whole number, or tap Unlimited."
_PLANS_PROMPT_TEXT = "Select which plans this code applies to:"
_NEED_ONE_PLAN_TEXT = "⚠️ Select at least one plan before continuing."
_VISIBILITY_PROMPT_TEXT = "Should this code be public (auto-applied) or private (typed only)?"


async def _scope_text(session: AsyncSession, discount: DiscountCode) -> str:
    if discount.plan_ids is None:
        return "All plans"
    names = []
    for pid in (int(x) for x in discount.plan_ids.split(",")):
        plan = await get_plan(session, pid)
        names.append(plan.name if plan is not None else f"#{pid}")
    return ", ".join(names)


def _detail_text(discount: DiscountCode, scope: str) -> str:
    limit = "Unlimited" if discount.usage_limit is None else str(discount.usage_limit)
    status = "Active" if discount.is_active else "Inactive"
    visibility = "Public" if discount.is_public else "Private"
    return (
        f"🏷 <b>{discount.code}</b>\n"
        f"Discount: {discount.percent}%\n"
        f"Usage: {discount.used_count}/{limit}\n"
        f"Plans: {scope}\n"
        f"Status: {status} · {visibility}"
    )


async def _render_list() -> tuple[str, InlineKeyboardMarkup]:
    async with async_session_maker() as session:
        discounts = await list_discount_codes(session)
    return _LIST_TEXT, discount_list_keyboard(discounts)


@router.callback_query(F.data == "adm:discounts")
async def discounts_list_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, keyboard = await _render_list()
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:view:"))
async def discount_view_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        discount = await get_discount_code(session, discount_id)
        if discount is None:
            text, keyboard = await _render_list()
        else:
            scope = await _scope_text(session, discount)
            text, keyboard = _detail_text(discount, scope), discount_detail_keyboard(discount)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:toggle:"))
async def discount_toggle_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        current = await get_discount_code(session, discount_id)
        discount = await set_discount_active(session, discount_id, not current.is_active) if current is not None else None
        if discount is None:
            text, keyboard = await _render_list()
        else:
            scope = await _scope_text(session, discount)
            text, keyboard = _detail_text(discount, scope), discount_detail_keyboard(discount)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:delete:") & ~F.data.endswith(":confirm"))
async def discount_delete_prompt_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-1])
    if callback.message is not None:
        await callback.message.edit_text(
            "🗑 Delete this discount code? This can't be undone.",
            reply_markup=discount_delete_confirm_keyboard(discount_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:delete:") & F.data.endswith(":confirm"))
async def discount_delete_confirm_cb(callback: CallbackQuery) -> None:
    discount_id = int(callback.data.split(":")[-2])
    async with async_session_maker() as session:
        await delete_discount_code(session, discount_id)
    text, keyboard = await _render_list()
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("🗑 Deleted.")


@router.callback_query(F.data == "adm:discounts:new")
async def discount_new_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DiscountCodeStates.name)
    await state.update_data(editing_id=None)
    if callback.message is not None:
        await callback.message.edit_text(_NAME_PROMPT_TEXT, reply_markup=wizard_cancel_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("adm:discounts:edit:"))
async def discount_edit_cb(callback: CallbackQuery, state: FSMContext) -> None:
    discount_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        discount = await get_discount_code(session, discount_id)
    if discount is None:
        text, keyboard = await _render_list()
        if callback.message is not None:
            await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
        return

    # Editing skips the name step (code text is immutable) and pre-fills
    # every other field, matching AloBot's editing_id-conditional flow.
    await state.set_state(DiscountCodeStates.percent)
    await state.update_data(
        editing_id=discount.id,
        code=discount.code,
        selected_plan_ids=[int(p) for p in discount.plan_ids.split(",")] if discount.plan_ids else [],
    )
    if callback.message is not None:
        await callback.message.edit_text(
            f"Current percent: {discount.percent}%\n\n{_PERCENT_PROMPT_TEXT}", reply_markup=wizard_cancel_keyboard()
        )
    await callback.answer()


@router.message(DiscountCodeStates.name)
async def discount_wizard_receive_name(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer(_NAME_PROMPT_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    code = normalize_discount_code(raw)
    async with async_session_maker() as session:
        existing = await get_discount_code_by_name(session, code)
    if existing is not None:
        await message.answer(_DUPLICATE_CODE_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    await state.update_data(code=code)
    await state.set_state(DiscountCodeStates.percent)
    await message.answer(_PERCENT_PROMPT_TEXT, reply_markup=wizard_cancel_keyboard())


@router.message(DiscountCodeStates.percent)
async def discount_wizard_receive_percent(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        percent = Decimal(raw)
    except InvalidOperation:
        await message.answer(_INVALID_PERCENT_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    if not (Decimal("0") < percent <= Decimal("100")):
        await message.answer(_INVALID_PERCENT_TEXT, reply_markup=wizard_cancel_keyboard())
        return
    await state.update_data(percent=str(percent))
    await state.set_state(DiscountCodeStates.usage_limit)
    await message.answer(_USAGE_LIMIT_PROMPT_TEXT, reply_markup=wizard_usage_limit_keyboard())


async def _enter_plans_step(state: FSMContext) -> tuple[str, InlineKeyboardMarkup]:
    data = await state.get_data()
    await state.set_state(DiscountCodeStates.plans)
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    selected = data.get("selected_plan_ids", [])
    return _PLANS_PROMPT_TEXT, wizard_plans_keyboard(plans, selected)


@router.message(DiscountCodeStates.usage_limit)
async def discount_wizard_receive_usage_limit(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(_INVALID_USAGE_LIMIT_TEXT, reply_markup=wizard_usage_limit_keyboard())
        return
    await state.update_data(usage_limit=int(raw))
    text, keyboard = await _enter_plans_step(state)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(DiscountCodeStates.usage_limit, F.data == "adm:discounts:wizard:unlimited")
async def discount_wizard_unlimited_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(usage_limit=None)
    text, keyboard = await _enter_plans_step(state)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(DiscountCodeStates.plans, F.data.startswith("adm:discounts:wizard:plan:"))
async def discount_wizard_toggle_plan_cb(callback: CallbackQuery, state: FSMContext) -> None:
    plan_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    selected: list[int] = list(data.get("selected_plan_ids", []))
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    await state.update_data(selected_plan_ids=selected)
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    if callback.message is not None:
        await callback.message.edit_text(_PLANS_PROMPT_TEXT, reply_markup=wizard_plans_keyboard(plans, selected))
    await callback.answer()


@router.callback_query(DiscountCodeStates.plans, F.data == "adm:discounts:wizard:allplans")
async def discount_wizard_toggle_all_plans_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        plans = await list_plans(session, active_only=True)
    data = await state.get_data()
    selected = data.get("selected_plan_ids", [])
    new_selected: list[int] = [] if len(selected) == len(plans) else [p.id for p in plans]
    await state.update_data(selected_plan_ids=new_selected)
    if callback.message is not None:
        await callback.message.edit_text(_PLANS_PROMPT_TEXT, reply_markup=wizard_plans_keyboard(plans, new_selected))
    await callback.answer()


@router.callback_query(DiscountCodeStates.plans, F.data == "adm:discounts:wizard:plansdone")
async def discount_wizard_plans_done_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("selected_plan_ids"):
        await callback.answer(_NEED_ONE_PLAN_TEXT, show_alert=True)
        return
    await state.set_state(DiscountCodeStates.visibility)
    if callback.message is not None:
        await callback.message.edit_text(_VISIBILITY_PROMPT_TEXT, reply_markup=wizard_visibility_keyboard())
    await callback.answer()


@router.callback_query(
    DiscountCodeStates.visibility, F.data.in_({"adm:discounts:wizard:public", "adm:discounts:wizard:private"})
)
async def discount_wizard_finish_cb(callback: CallbackQuery, state: FSMContext) -> None:
    is_public = callback.data.endswith(":public")
    data = await state.get_data()
    editing_id = data.get("editing_id")

    async with async_session_maker() as session:
        all_plans = await list_plans(session, active_only=True)
        selected: list[int] = data["selected_plan_ids"]
        plan_ids = None if len(selected) == len(all_plans) else selected
        percent = Decimal(data["percent"])
        usage_limit = data.get("usage_limit")

        if editing_id is None:
            discount = await create_discount_code(
                session, code=data["code"], percent=percent, usage_limit=usage_limit,
                plan_ids=plan_ids, is_public=is_public,
            )
        else:
            discount = await update_discount_code(
                session, editing_id, percent=percent, usage_limit=usage_limit,
                plan_ids=plan_ids, is_public=is_public,
            )
        scope = await _scope_text(session, discount) if discount is not None else ""

    await state.clear()
    if discount is not None and callback.message is not None:
        await callback.message.edit_text(_detail_text(discount, scope), reply_markup=discount_detail_keyboard(discount))
    await callback.answer()
```

- [ ] **Step 6: Wire the router into `app/main.py`**

Change:
```python
from app.bot.handlers import admin, admin_block, admin_renew, broadcast, fallback, trial, tutorial_admin, users
```
to:
```python
from app.bot.handlers import admin, admin_block, admin_discounts, admin_renew, broadcast, fallback, trial, tutorial_admin, users
```

Change:
```python
    dp.include_router(admin.router)
    dp.include_router(admin_block.router)
    dp.include_router(admin_renew.router)
    dp.include_router(broadcast.router)
```
to:
```python
    dp.include_router(admin.router)
    dp.include_router(admin_block.router)
    dp.include_router(admin_discounts.router)
    dp.include_router(admin_renew.router)
    dp.include_router(broadcast.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_admin_discounts.py`, and no regression elsewhere.

- [ ] **Step 8: Commit**

```bash
git add app/bot/states/admin_discounts.py app/bot/keyboards/admin_discounts.py app/bot/handlers/admin_discounts.py \
        app/main.py tests/functional/test_admin_discounts.py
git commit -m "feat: discount code admin CRUD wizard"
```

---

### Task 7: Support contact config + IBSng group sync

**Files:**
- Create: `app/bot/states/admin_settings.py`
- Create: `app/bot/keyboards/admin_settings.py`
- Create: `app/bot/handlers/admin_settings.py`
- Modify: `app/main.py`
- Test: `tests/functional/test_admin_settings.py`

**Interfaces:**
- Consumes: `IsFullAdmin` from `app.bot.filters.admin` (Task 1). `set_config` from `app.services.app_config` (existing). `sync_groups` from `app.services.groups` (existing). `IBSngClient`, `IBSngError` from `app.services.ibsng` (existing).
- Produces: nothing consumed by a later task — this is the plan's last task.

- [ ] **Step 1: Write the failing tests**

Create `tests/functional/test_admin_settings.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_full_admin_cannot_edit_support_contact(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=521, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(521, "adm:settings:support"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("support contact" in c[1].get("text", "").lower() for c in edited)


@pytest.mark.asyncio
async def test_full_admin_sets_support_contact(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:support"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "@homeland_support"))

    async with async_session_maker() as session:
        assert await get_config(session, "support_username") == "@homeland_support"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("@homeland_support" in c[1].get("text", "") for c in sent)


@pytest.mark.asyncio
async def test_empty_support_contact_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:support"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "   "))

    async with async_session_maker() as session:
        assert await get_config(session, "support_username") is None


@pytest.mark.asyncio
async def test_sync_groups_reports_count_and_excludes_alobot_groups(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.groups import list_groups

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:syncgroups"))

    async with async_session_maker() as session:
        groups = await list_groups(session)
    assert all("Iran" in g.name for g in groups)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert f"synced {len(groups)}" in edited[-1][1]["text"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test` (target `tests/functional/test_admin_settings.py`)
Expected: FAIL — `adm:settings:support` / `adm:settings:syncgroups` have no handler yet.

- [ ] **Step 3: Create the settings-flow state and keyboards**

`app/bot/states/admin_settings.py`:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditSupportStates(StatesGroup):
    support_username = State()
```

`app/bot/keyboards/admin_settings.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def settings_edit_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()


def back_to_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Create the settings handler**

`app/bot/handlers/admin_settings.py`:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin_settings import back_to_settings_keyboard, settings_edit_cancel_keyboard
from app.bot.states.admin_settings import EditSupportStates
from app.db.session import async_session_maker
from app.services.app_config import set_config
from app.services.groups import sync_groups
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError

router = Router(name="admin_settings")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_SUPPORT_PROMPT_TEXT = "Send the support contact (e.g. @homeland_support):"
_EMPTY_SUPPORT_TEXT = "⚠️ Send a non-empty value."
_SYNC_FAILED_TEXT = "⚠️ Could not reach IBSng to sync groups. Please try again shortly."


@router.callback_query(F.data == "adm:settings:support")
async def settings_edit_support_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditSupportStates.support_username)
    if callback.message is not None:
        await callback.message.edit_text(_SUPPORT_PROMPT_TEXT, reply_markup=settings_edit_cancel_keyboard())
    await callback.answer()


@router.message(EditSupportStates.support_username)
async def settings_receive_support_username(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer(_EMPTY_SUPPORT_TEXT, reply_markup=settings_edit_cancel_keyboard())
        return
    async with async_session_maker() as session:
        await set_config(session, "support_username", value)
    await state.clear()
    await message.answer(f"✅ Support contact set to {value}.", reply_markup=back_to_settings_keyboard())


@router.callback_query(F.data == "adm:settings:syncgroups")
async def settings_sync_groups_cb(callback: CallbackQuery) -> None:
    try:
        async with async_session_maker() as session, IBSngClient() as client:
            groups = await sync_groups(session, client)
    except IBSngError:
        if callback.message is not None:
            await callback.message.edit_text(_SYNC_FAILED_TEXT, reply_markup=back_to_settings_keyboard())
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(
            f"🔄 Synced {len(groups)} Homeland group(s).", reply_markup=back_to_settings_keyboard()
        )
    await callback.answer()
```

- [ ] **Step 5: Wire the router into `app/main.py`**

Change:
```python
from app.bot.handlers import admin, admin_block, admin_discounts, admin_renew, broadcast, fallback, trial, tutorial_admin, users
```
to:
```python
from app.bot.handlers import (
    admin, admin_block, admin_discounts, admin_renew, admin_settings, broadcast,
    fallback, trial, tutorial_admin, users,
)
```

Change:
```python
    dp.include_router(admin.router)
    dp.include_router(admin_block.router)
    dp.include_router(admin_discounts.router)
    dp.include_router(admin_renew.router)
    dp.include_router(broadcast.router)
```
to:
```python
    dp.include_router(admin.router)
    dp.include_router(admin_block.router)
    dp.include_router(admin_discounts.router)
    dp.include_router(admin_renew.router)
    dp.include_router(admin_settings.router)
    dp.include_router(broadcast.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `make test`
Expected: PASS — all of `tests/functional/test_admin_settings.py`, and the full suite green from a fresh state.

- [ ] **Step 7: Commit**

```bash
git add app/bot/states/admin_settings.py app/bot/keyboards/admin_settings.py app/bot/handlers/admin_settings.py \
        app/main.py tests/functional/test_admin_settings.py
git commit -m "feat: admin settings — support contact config and IBSng group sync"
```

---

## Self-Review

**Spec coverage** (`docs/superpowers/specs/2026-09-15-admin-panel-design.md`):
- §2 Auth tiers → Task 1 (`IsSalesAdmin`, `IsFullAdmin`, inline `has_level(..., "support")` checks throughout).
- §3 Navigation shell (`adm:root`, `adm:users`, `adm:settings`, `adm:tutorials` adapter) → Task 1.
- §4 Broadcast → Task 2.
- §5 Block/unblock → Task 3.
- §6 Admin renew-by-username (`IBSngClient.renew_user`, `renew_and_change_group`) → Task 4.
- §7 Discount codes (model, service, admin CRUD wizard) → Tasks 5 and 6.
- §8 Support contact config + IBSng group sync → Task 7.
- §9 Out of scope (sales reports, usage logging, admin-management UI, reseller/channel/card settings) → deliberately not built anywhere in this plan, matching the spec.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code; no test asserts a tautology.

**Type consistency check:**
- `IBSngClient.renew_user(*, username: str) -> None` (Task 4) matches its one call site in `vpn_users.renew_and_change_group` (Task 4) and is never referenced elsewhere.
- `vpn_users.renew_and_change_group(session, client, *, username, new_group_name, new_plan_id, new_data_cap_mb) -> None` (Task 4) matches its one call site in `app/bot/handlers/admin_renew.py` (Task 4).
- `discounts.create_discount_code`/`update_discount_code` both take `plan_ids: list[int] | None` (Task 5) and are called with `list[int] | None` from `app/bot/handlers/admin_discounts.py` (Task 6) — consistent.
- `admin_root_menu`, `admin_users_menu`, `admin_settings_menu` (Task 1) keep identical signatures everywhere they're imported (Tasks 2 and later only import `admin_root_menu`, for the broadcast-cancel screen).
- `list_blocked_users(session) -> list[BotUser]` (Task 3) matches its one call site in `app/bot/handlers/admin_block.py` (Task 3).
- Every new router is registered in `app/main.py` in the same task that creates it (except Task 5, which adds no router) — verified against the cumulative `app/main.py` snippets in Steps 6/11/6/5 of Tasks 1, 2, 3, 4, 6, 7 respectively, which stay mutually consistent (each task's "before" snippet matches the previous task's "after" snippet).
