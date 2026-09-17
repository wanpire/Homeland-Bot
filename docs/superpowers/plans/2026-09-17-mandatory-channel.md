# Mandatory Channel Membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate every bot interaction behind membership in zero or more admin-configured public Telegram channels ("forced subscription"), with an admin-facing UI to configure it.

**Architecture:** A new outer middleware (`MandatoryChannelMiddleware`, mirroring the existing `BlockedUserMiddleware` exactly) checks channel membership via `Bot.get_chat_member` before any handler runs; a thin service module (`app/services/mandatory_channel.py`) stores the channel list and on/off flag in the existing free-form `app_config` key/value store; a new admin-settings screen lets a full admin view and edit both.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, PostgreSQL, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-17-mandatory-channel-design.md`

## Global Constraints

- Admins (`has_level(session, user_id, "support")` or higher) are always exempt from the membership check — a misconfigured channel must never lock the admin panel itself. (Spec §3.)
- A channel membership check that itself fails (bot not an admin of that channel, transient Telegram API error) fails OPEN — the request is allowed through, not blocked. A broken config must never take down the whole bot for every user. (Spec §3.)
- A `ChatMember.status` of `"member"`, `"administrator"`, `"creator"`, or `"restricted"` counts as joined. Only `"left"`/`"kicked"` (or the API call raising) count as not joined. (Spec §3.)
- No schema/migration changes — both new config keys (`mandatory_channel_usernames`, `mandatory_channel_enabled`) go through the existing `app_config` key/value table via `get_config`/`set_config`. (Spec §2.)
- Two distinct screens, not one: `adm:settings:channel` (status view: current channels + on/off state) and `adm:settings:channel:edit` (the text-prompt to change the channel list). Do not collapse these — the spec's own self-review caught and fixed exactly this collision. (Spec §4.)
- English-only user-facing text. (Project-wide convention, `CLAUDE.md`.)
- New middleware registers in `app/main.py` immediately after `BlockedUserMiddleware()`, before router registration — so an already-blocked user never triggers a `get_chat_member` API call. (Spec §3.)

---

## File Structure

- **Create** `app/services/mandatory_channel.py` — config read/write helpers.
- **Create** `app/bot/keyboards/mandatory_channel.py` — the join-prompt keyboard.
- **Create** `app/bot/middlewares/mandatory_channel.py` — the enforcement middleware.
- **Modify** `app/main.py` — register the new middleware.
- **Modify** `app/bot/states/admin_settings.py` — add `EditMandatoryChannelStates`.
- **Modify** `app/bot/handlers/admin_settings.py` — add the status/edit/toggle handlers.
- **Modify** `app/bot/keyboards/admin.py` — add the "📢 Mandatory Channel" entry to `admin_settings_menu()`.
- **Create** `tests/functional/test_mandatory_channel.py` — middleware enforcement tests.
- **Modify** `tests/functional/test_admin_settings.py` if it exists, else **create** it — admin UI tests (check which applies when starting the task).

---

## Task 1: Config service, enforcement middleware, and process wiring

**Files:**
- Create: `app/services/mandatory_channel.py`
- Create: `app/bot/keyboards/mandatory_channel.py`
- Create: `app/bot/middlewares/mandatory_channel.py`
- Modify: `app/main.py`
- Test: `tests/functional/test_mandatory_channel.py`

**Interfaces:**
- Produces: `get_mandatory_channels(session) -> list[str]`, `set_mandatory_channels(session, usernames: list[str]) -> None`, `is_mandatory_channel_enabled(session) -> bool`, `set_mandatory_channel_enabled(session, enabled: bool) -> None` (all `app/services/mandatory_channel.py`) — Task 2's admin UI calls all four directly. `join_channels_keyboard(missing_usernames: list[str]) -> InlineKeyboardMarkup` (`app/bot/keyboards/mandatory_channel.py`) — used only by the middleware itself; no later task consumes it. `MandatoryChannelMiddleware` (`app/bot/middlewares/mandatory_channel.py`) — registered in `app/main.py`, not imported anywhere else.

- [ ] **Step 1: Write the failing tests for the config service**

Create `tests/functional/test_mandatory_channel.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from aiogram import Bot

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_get_mandatory_channels_defaults_to_empty() -> None:
    from app.services.mandatory_channel import get_mandatory_channels

    async with async_session_maker() as session:
        assert await get_mandatory_channels(session) == []


@pytest.mark.asyncio
async def test_set_and_get_mandatory_channels_strips_at_signs() -> None:
    from app.services.mandatory_channel import get_mandatory_channels, set_mandatory_channels

    async with async_session_maker() as session:
        await set_mandatory_channels(session, ["@homeland_channel", "homeland_news"])

    async with async_session_maker() as session:
        assert await get_mandatory_channels(session) == ["homeland_channel", "homeland_news"]


@pytest.mark.asyncio
async def test_is_mandatory_channel_enabled_defaults_false() -> None:
    from app.services.mandatory_channel import is_mandatory_channel_enabled

    async with async_session_maker() as session:
        assert await is_mandatory_channel_enabled(session) is False


@pytest.mark.asyncio
async def test_set_mandatory_channel_enabled_round_trips() -> None:
    from app.services.mandatory_channel import is_mandatory_channel_enabled, set_mandatory_channel_enabled

    async with async_session_maker() as session:
        await set_mandatory_channel_enabled(session, True)
    async with async_session_maker() as session:
        assert await is_mandatory_channel_enabled(session) is True

    async with async_session_maker() as session:
        await set_mandatory_channel_enabled(session, False)
    async with async_session_maker() as session:
        assert await is_mandatory_channel_enabled(session) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_mandatory_channel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.mandatory_channel'`

- [ ] **Step 3: Create `app/services/mandatory_channel.py`**

```python
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_config import get_config, set_config

_USERNAMES_KEY = "mandatory_channel_usernames"
_ENABLED_KEY = "mandatory_channel_enabled"


async def get_mandatory_channels(session: AsyncSession) -> list[str]:
    """Returns the configured channel usernames (no leading @), or an
    empty list if none are set."""
    raw = await get_config(session, _USERNAMES_KEY)
    if not raw:
        return []
    return [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]


async def set_mandatory_channels(session: AsyncSession, usernames: list[str]) -> None:
    await set_config(session, _USERNAMES_KEY, ",".join(u.strip().lstrip("@") for u in usernames if u.strip()))


async def is_mandatory_channel_enabled(session: AsyncSession) -> bool:
    return (await get_config(session, _ENABLED_KEY)) == "true"


async def set_mandatory_channel_enabled(session: AsyncSession, enabled: bool) -> None:
    await set_config(session, _ENABLED_KEY, "true" if enabled else "false")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/functional/test_mandatory_channel.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatory_channel.py tests/functional/test_mandatory_channel.py
git commit -m "feat: add mandatory-channel config service"
```

- [ ] **Step 6: Write the failing tests for the middleware**

Append to `tests/functional/test_mandatory_channel.py`:

```python
async def _enable_with_channels(*usernames: str) -> None:
    from app.services.mandatory_channel import set_mandatory_channel_enabled, set_mandatory_channels

    async with async_session_maker() as session:
        await set_mandatory_channels(session, list(usernames))
        await set_mandatory_channel_enabled(session, True)


@pytest.mark.asyncio
async def test_disabled_feature_lets_everything_through(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "welcome" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_no_channels_configured_lets_everything_through(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.mandatory_channel import set_mandatory_channel_enabled

    async with async_session_maker() as session:
        await set_mandatory_channel_enabled(session, True)

    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "welcome" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_non_member_callback_is_blocked_with_join_keyboard(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    await _enable_with_channels("homeland_channel")

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(status="left")

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "join" in edited[0][1]["text"].lower()
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    join_button = next(b for b in buttons if "homeland_channel" in b["text"])
    assert join_button["url"] == "https://t.me/homeland_channel"
    assert any(b["text"] == "✅ I've Joined" and b["callback_data"] == "menu:root" for b in buttons)

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert len(answered) == 1


@pytest.mark.asyncio
async def test_non_member_message_is_blocked_with_new_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    await _enable_with_channels("homeland_channel")

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(status="left")

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    await dispatcher.feed_update(bot, make_message_update(999, "/start"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "join" in sent[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_member_status_passes_through(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    await _enable_with_channels("homeland_channel")

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(status="member")

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "welcome" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_restricted_status_counts_as_joined(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    await _enable_with_channels("homeland_channel")

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(status="restricted")

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "welcome" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_admin_is_exempt_even_when_not_a_member(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    await _enable_with_channels("homeland_channel")

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(status="left")

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "welcome" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_api_error_fails_open(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aiogram.exceptions import TelegramBadRequest

    await _enable_with_channels("homeland_channel")

    async def _boom(self: Bot, *, chat_id: str, user_id: int):
        raise TelegramBadRequest(method=None, message="member list is inaccessible")

    monkeypatch.setattr(Bot, "get_chat_member", _boom)

    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "welcome" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_lists_only_missing_channels(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    await _enable_with_channels("chan_missing", "chan_joined")

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        status = "left" if chat_id == "@chan_missing" else "member"
        return SimpleNamespace(status=status)

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    join_buttons = [b for b in buttons if b["text"].startswith("📢 Join")]
    assert len(join_buttons) == 1
    assert "chan_missing" in join_buttons[0]["text"]
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `pytest tests/functional/test_mandatory_channel.py -v -k "not (get_mandatory or set_and_get or is_mandatory or set_mandatory)"`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.bot.middlewares.mandatory_channel'`

- [ ] **Step 8: Create `app/bot/keyboards/mandatory_channel.py`**

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def join_channels_keyboard(missing_usernames: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for username in missing_usernames:
        builder.button(text=f"📢 Join @{username}", url=f"https://t.me/{username}")
    builder.button(text="✅ I've Joined", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 9: Create `app/bot/middlewares/mandatory_channel.py`**

```python
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.bot.keyboards.mandatory_channel import join_channels_keyboard
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.mandatory_channel import get_mandatory_channels, is_mandatory_channel_enabled

logger = logging.getLogger(__name__)

_JOINED_STATUSES = {"member", "administrator", "creator", "restricted"}
_JOIN_PROMPT_TEXT = (
    "📢 <b>Join our channel to continue</b>\n\n"
    "Please join the channel(s) below, then tap \"I've Joined\"."
)


class MandatoryChannelMiddleware(BaseMiddleware):
    """Blocks every interaction for a non-member of the configured
    channel(s), when the feature is enabled. Admins are always exempt -
    a misconfigured channel must never lock the admin panel itself. A
    channel membership check that itself fails (bot not an admin of
    that channel, transient API error) fails OPEN - a broken config
    must never take down the whole bot for every user."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is None or inner.from_user is None:
            return await handler(event, data)

        user_id = inner.from_user.id
        async with async_session_maker() as session:
            if await has_level(session, user_id, "support"):
                return await handler(event, data)
            if not await is_mandatory_channel_enabled(session):
                return await handler(event, data)
            channels = await get_mandatory_channels(session)
            if not channels:
                return await handler(event, data)

        missing = [username for username in channels if not await self._is_member(inner, user_id, username)]
        if not missing:
            return await handler(event, data)

        keyboard = join_channels_keyboard(missing)
        if isinstance(inner, CallbackQuery):
            if inner.message is not None:
                await inner.message.edit_text(_JOIN_PROMPT_TEXT, reply_markup=keyboard)
            await inner.answer()
        else:
            await inner.answer(_JOIN_PROMPT_TEXT, reply_markup=keyboard)
        return None

    @staticmethod
    async def _is_member(inner: Message | CallbackQuery, user_id: int, username: str) -> bool:
        try:
            member = await inner.bot.get_chat_member(chat_id=f"@{username}", user_id=user_id)
        except TelegramAPIError as exc:
            logger.warning("Mandatory channel check failed for @%s: %s - failing open", username, exc)
            return True
        return member.status in _JOINED_STATUSES
```

- [ ] **Step 10: Wire the middleware into `app/main.py`**

Change:

```python
from app.bot.middlewares.blocked_user import BlockedUserMiddleware
from app.bot.middlewares.private_chat_only import PrivateChatOnlyMiddleware
from app.bot.middlewares.user_tracking import UserTrackingMiddleware
```

to:

```python
from app.bot.middlewares.blocked_user import BlockedUserMiddleware
from app.bot.middlewares.mandatory_channel import MandatoryChannelMiddleware
from app.bot.middlewares.private_chat_only import PrivateChatOnlyMiddleware
from app.bot.middlewares.user_tracking import UserTrackingMiddleware
```

Change:

```python
    dp.update.outer_middleware(PrivateChatOnlyMiddleware())
    dp.update.outer_middleware(UserTrackingMiddleware())
    dp.update.outer_middleware(BlockedUserMiddleware())
```

to:

```python
    dp.update.outer_middleware(PrivateChatOnlyMiddleware())
    dp.update.outer_middleware(UserTrackingMiddleware())
    dp.update.outer_middleware(BlockedUserMiddleware())
    dp.update.outer_middleware(MandatoryChannelMiddleware())
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `pytest tests/functional/test_mandatory_channel.py -v`
Expected: PASS (12 tests total in the file)

- [ ] **Step 12: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green. Pay particular attention to any pre-existing test that asserts on `fake_session.calls` counts right after `dispatcher.feed_update` for a non-admin telegram_id — since `MandatoryChannelMiddleware` is disabled by default (no config set until Task 2's UI or these tests explicitly enable it), no pre-existing test should be affected, but confirm.

- [ ] **Step 13: Commit**

```bash
git add app/bot/keyboards/mandatory_channel.py app/bot/middlewares/mandatory_channel.py app/main.py tests/functional/test_mandatory_channel.py
git commit -m "feat: add mandatory-channel enforcement middleware"
```

---

## Task 2: Admin settings UI

**Files:**
- Modify: `app/bot/states/admin_settings.py`
- Modify: `app/bot/handlers/admin_settings.py`
- Modify: `app/bot/keyboards/admin.py`
- Test: `tests/functional/test_admin_settings.py` (check whether this file exists already; if so append to it, matching its existing import/helper style — if not, create it following `tests/functional/test_admin_admins.py`'s structure as the closest precedent: `FAKE_ADMIN_ID`, `make_callback_update`, `make_message_update`, `dispatcher`/`bot`/`fake_session` fixtures)

**Interfaces:**
- Consumes: `get_mandatory_channels`, `set_mandatory_channels`, `is_mandatory_channel_enabled`, `set_mandatory_channel_enabled` (Task 1, `app/services/mandatory_channel.py`).
- Produces: nothing consumed by a later task — this is the final task in this plan.

- [ ] **Step 1: Check for an existing admin_settings test file**

Run: `ls tests/functional/test_admin_settings.py 2>/dev/null && echo EXISTS || echo MISSING`

If `MISSING`, create the file with this header before Step 2's test bodies:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession
```

If `EXISTS`, read the file first and add the imports above only if missing (don't duplicate any that are already there), then append the tests from Step 2 to the end of the existing file.

- [ ] **Step 2: Write the failing tests for the channel status screen**

```python
@pytest.mark.asyncio
async def test_channel_status_shows_disabled_by_default(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "disabled" in text.lower()
    assert "none set" in text.lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "✏️ Edit Channels" in buttons
    assert "🟢 Turn On" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_non_full_admin_cannot_access_channel_settings(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.admin_users import add_admin

    async with async_session_maker() as session:
        await add_admin(session, 601, "sales")

    await dispatcher.feed_update(bot, make_callback_update(601, "adm:settings:channel"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_admin_settings_menu_includes_mandatory_channel_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📢 Mandatory Channel" in buttons
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/functional/test_admin_settings.py -v -k channel`
Expected: FAIL — `"adm:settings:channel"` isn't handled yet, so `admin_fallback`'s catch-all (or no handler at all) leaves `fake_session.calls` empty for `editMessageText`, and `admin_settings_menu()` doesn't have the new button yet.

- [ ] **Step 4: Add `EditMandatoryChannelStates` to `app/bot/states/admin_settings.py`**

Change:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditSupportStates(StatesGroup):
    support_username = State()
```

to:

```python
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditSupportStates(StatesGroup):
    support_username = State()


class EditMandatoryChannelStates(StatesGroup):
    channels = State()
```

- [ ] **Step 5: Add the "📢 Mandatory Channel" button to `app/bot/keyboards/admin.py`**

Change:

```python
def admin_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

to:

```python
def admin_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="📢 Mandatory Channel", callback_data="adm:settings:channel")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 6: Add the channel handlers to `app/bot/handlers/admin_settings.py`**

Change the imports at the top — from:

```python
from __future__ import annotations

import html

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
```

to:

```python
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin_settings import back_to_settings_keyboard, settings_edit_cancel_keyboard
from app.bot.states.admin_settings import EditMandatoryChannelStates, EditSupportStates
from app.db.session import async_session_maker
from app.services.app_config import set_config
from app.services.groups import sync_groups
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.mandatory_channel import (
    get_mandatory_channels,
    is_mandatory_channel_enabled,
    set_mandatory_channel_enabled,
    set_mandatory_channels,
)
```

Append these constants and handlers to the end of the file:

```python
_CHANNEL_PROMPT_TEXT = (
    "Send the channel username(s) to require, comma-separated, without @ "
    "(e.g. homeland_channel, homeland_news). Send \"clear\" to remove all."
)
_EMPTY_CHANNELS_TEXT = "⚠️ Send a non-empty value."


async def _channel_status_text(session: AsyncSession) -> str:
    channels = await get_mandatory_channels(session)
    enabled = await is_mandatory_channel_enabled(session)
    state_line = "🟢 Enabled" if enabled else "🔴 Disabled"
    channels_line = ", ".join(f"@{c}" for c in channels) if channels else "(none set)"
    return f"📢 <b>Mandatory Channel</b>\n\nState: {state_line}\nChannels: {channels_line}"


def _channel_settings_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit Channels", callback_data="adm:settings:channel:edit")
    builder.button(
        text="🔴 Turn Off" if enabled else "🟢 Turn On", callback_data="adm:settings:channel:toggle"
    )
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "adm:settings:channel")
async def settings_channel_status_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        enabled = await is_mandatory_channel_enabled(session)
        text = await _channel_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_channel_settings_keyboard(enabled=enabled))
    await callback.answer()


@router.callback_query(F.data == "adm:settings:channel:edit")
async def settings_edit_channel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditMandatoryChannelStates.channels)
    if callback.message is not None:
        async with async_session_maker() as session:
            text = await _channel_status_text(session)
        await callback.message.edit_text(
            f"{text}\n\n{_CHANNEL_PROMPT_TEXT}", reply_markup=settings_edit_cancel_keyboard()
        )
    await callback.answer()


@router.message(EditMandatoryChannelStates.channels)
async def settings_receive_channels(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    async with async_session_maker() as session:
        if raw.lower() == "clear":
            await set_mandatory_channels(session, [])
        else:
            usernames = [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]
            if not usernames:
                await message.answer(_EMPTY_CHANNELS_TEXT, reply_markup=settings_edit_cancel_keyboard())
                return
            await set_mandatory_channels(session, usernames)
    await state.clear()
    async with async_session_maker() as session:
        enabled = await is_mandatory_channel_enabled(session)
        text = await _channel_status_text(session)
    await message.answer(f"✅ Channels updated.\n\n{text}", reply_markup=_channel_settings_keyboard(enabled=enabled))


@router.callback_query(F.data == "adm:settings:channel:toggle")
async def settings_toggle_channel_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        currently_enabled = await is_mandatory_channel_enabled(session)
        await set_mandatory_channel_enabled(session, not currently_enabled)
        enabled = not currently_enabled
        text = await _channel_status_text(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_channel_settings_keyboard(enabled=enabled))
    await callback.answer()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/functional/test_admin_settings.py -v -k channel`
Expected: PASS (3 tests from Step 2)

- [ ] **Step 8: Write the failing tests for editing and toggling**

Append to the same test file:

```python
@pytest.mark.asyncio
async def test_channel_edit_flow_sets_channels(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.mandatory_channel import get_mandatory_channels

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "homeland_channel, homeland_news"))

    async with async_session_maker() as session:
        assert await get_mandatory_channels(session) == ["homeland_channel", "homeland_news"]

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "updated" in sent[-1][1]["text"].lower()
    assert "homeland_channel" in sent[-1][1]["text"]


@pytest.mark.asyncio
async def test_channel_edit_rejects_empty_input(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "   "))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("non-empty" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_channel_edit_clear_removes_all(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.mandatory_channel import get_mandatory_channels, set_mandatory_channels

    async with async_session_maker() as session:
        await set_mandatory_channels(session, ["homeland_channel"])

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "clear"))

    async with async_session_maker() as session:
        assert await get_mandatory_channels(session) == []


@pytest.mark.asyncio
async def test_channel_toggle_flips_state(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.mandatory_channel import is_mandatory_channel_enabled

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:toggle"))
    async with async_session_maker() as session:
        assert await is_mandatory_channel_enabled(session) is True
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔴 Turn Off" in buttons

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:toggle"))
    async with async_session_maker() as session:
        assert await is_mandatory_channel_enabled(session) is False
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🟢 Turn On" in buttons
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/functional/test_admin_settings.py -v`
Expected: PASS (all tests in the file, including every pre-existing one if the file already existed).

- [ ] **Step 10: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green.

- [ ] **Step 11: Commit**

```bash
git add app/bot/states/admin_settings.py app/bot/handlers/admin_settings.py app/bot/keyboards/admin.py tests/functional/test_admin_settings.py
git commit -m "feat: add mandatory-channel admin settings UI"
```

---

## Self-Review

**1. Spec coverage:**
- §1 (Summary) — Task 1's middleware implements the gate; Task 2's UI lets an admin actually configure it. Covered.
- §2 (Config) — Task 1 Step 3, verbatim. Covered.
- §3 (Membership check + middleware, including the fail-open/admin-exemption/restricted-status rules and the "no dedicated recheck handler" design) — Task 1 Steps 8-10, verbatim, with dedicated tests for each rule (admin exemption, fail-open, restricted-status, multi-channel). Covered.
- §4 (Admin settings UI, including the corrected two-screen split) — Task 2 Steps 4-6, verbatim; `adm:settings:channel` (status) and `adm:settings:channel:edit` (prompt) are two distinct handlers throughout, matching the spec's self-corrected routing exactly. Covered.
- §5 (Out of scope) — no task builds private-channel support, per-user join history, a pre-emptive channel-list display, or any caching/rate-limiting of `get_chat_member` — confirmed absent from both tasks' File Structure entries.

**2. Placeholder scan:** No "TBD"/"TODO"/"similar to Task N" patterns — every step's code is transcribed complete from the spec's own final, self-reviewed code blocks, with TDD scaffolding added around it. Task 2 Step 1's "check whether the file exists" step describes a real decision point (append vs. create) with the exact header to use either way, not a vague instruction.

**3. Type consistency:**
- `get_mandatory_channels(session) -> list[str]` / `set_mandatory_channels(session, usernames: list[str]) -> None` / `is_mandatory_channel_enabled(session) -> bool` / `set_mandatory_channel_enabled(session, enabled: bool) -> None` — defined once in Task 1 Step 3, imported and called with identical signatures in Task 1's middleware (Step 9) and Task 2's handlers (Step 6). No drift.
- `_channel_status_text(session: AsyncSession) -> str` and `_channel_settings_keyboard(*, enabled: bool) -> InlineKeyboardMarkup` — both defined once in Task 2 Step 6, called with matching argument shapes from all three handlers that use them (`settings_channel_status_cb`, `settings_edit_channel_cb`, `settings_receive_channels`, `settings_toggle_channel_cb`) — verified each call site passes `enabled` as a keyword argument matching the keyword-only signature.
- `adm:settings:channel` vs `adm:settings:channel:edit` — verified consistent everywhere: `admin_settings_menu()`'s new button points at `adm:settings:channel` (the status screen); `_channel_settings_keyboard`'s "✏️ Edit Channels" button points at `adm:settings:channel:edit`; `settings_channel_status_cb` is decorated `F.data == "adm:settings:channel"`; `settings_edit_channel_cb` is decorated `F.data == "adm:settings:channel:edit"`. No collision, matching the spec's self-corrected routing.
- `join_channels_keyboard(missing_usernames: list[str])` — defined once (Task 1 Step 8), called once (Task 1 Step 9's middleware) with the exact `missing` list already filtered to non-joined usernames — no signature drift.
