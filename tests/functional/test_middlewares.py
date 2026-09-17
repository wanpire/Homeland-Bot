"""End-to-end coverage for the three gating outer middlewares, driven
through the real Dispatcher (app.main.build_dispatcher) rather than by
calling the middleware objects directly - the point is to prove the
wiring order actually stops an update before it reaches a handler."""

from __future__ import annotations

from typing import Any

import pytest

from app.bot.handlers.users import WELCOME_TEXT
from app.db.session import async_session_maker
from app.services.bot_users import block_user
from tests.factories import (
    FAKE_ADMIN_ID,
    make_callback_update,
    make_group_message_update,
    make_message_update,
    seed_bot_user,
)
from tests.fakes.fake_bot_session import FakeBotSession

_BLOCKED_SNIPPET = "blocked from using this bot"


async def _seed_blocked_user(telegram_id: int) -> None:
    async with async_session_maker() as session:
        await seed_bot_user(session, telegram_id)
    async with async_session_maker() as session:
        await block_user(session, telegram_id)


@pytest.mark.asyncio
async def test_blocked_user_start_never_reaches_the_handler(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_blocked_user(5001)

    await dispatcher.feed_update(bot, make_message_update(5001, "/start"))

    sent = [call for call in fake_session.calls if call[0] == "sendMessage"]
    assert len(sent) == 1
    assert WELCOME_TEXT not in sent[0][1]["text"]
    assert _BLOCKED_SNIPPET in sent[0][1]["text"]


@pytest.mark.asyncio
async def test_blocked_user_callback_gets_an_alert_not_the_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_blocked_user(5002)

    await dispatcher.feed_update(bot, make_callback_update(5002, "menu:root"))

    assert [call for call in fake_session.calls if call[0] == "editMessageText"] == []
    answered = [call for call in fake_session.calls if call[0] == "answerCallbackQuery"]
    assert len(answered) == 1
    assert _BLOCKED_SNIPPET in answered[0][1]["text"]


@pytest.mark.asyncio
async def test_blocked_admin_is_exempt_and_still_gets_the_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A block must never be able to lock an admin out of the panel."""
    await _seed_blocked_user(FAKE_ADMIN_ID)

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/start"))

    sent = [call for call in fake_session.calls if call[0] == "sendMessage"]
    assert len(sent) == 1
    assert "Welcome to Homeland" in sent[0][1]["text"]
    buttons = [btn["text"] for row in sent[0][1]["reply_markup"]["inline_keyboard"] for btn in row]
    assert "🛠 Admin Panel" in buttons


@pytest.mark.asyncio
async def test_group_chat_message_is_dropped_silently(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_group_message_update(5003, "/start"))

    assert fake_session.calls == []


@pytest.mark.asyncio
async def test_group_chat_message_is_not_even_recorded_as_a_bot_user(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """PrivateChatOnlyMiddleware is registered first, so an ungated update
    never reaches UserTrackingMiddleware either."""
    from sqlalchemy import select

    from app.db.models.bot_user import BotUser

    await dispatcher.feed_update(bot, make_group_message_update(5004, "hello"))

    async with async_session_maker() as session:
        row = (
            await session.execute(select(BotUser).where(BotUser.telegram_id == 5004))
        ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_admin_ui_toggle_actually_gates_a_real_update_end_to_end(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the admin settings UI (Task 2) and the enforcement
    middleware (Task 1) are actually wired to the same config, not just
    unit-tested in isolation against each other's assumptions."""
    from types import SimpleNamespace

    from aiogram import Bot

    # Configure and enable via the real admin UI, not by calling the
    # service functions directly.
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "homeland_channel"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:toggle"))

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(status="left")

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(6001, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "join" in edited[0][1]["text"].lower()
    assert WELCOME_TEXT not in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_blocked_user_never_triggers_a_channel_membership_check(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the middleware registration order (BlockedUserMiddleware
    before MandatoryChannelMiddleware) - a blocked user must never cause
    a get_chat_member API call at all."""
    from aiogram import Bot
    from app.db.session import async_session_maker as make_session
    from app.services.mandatory_channel import set_mandatory_channel_enabled, set_mandatory_channels

    async with make_session() as session:
        await set_mandatory_channels(session, ["homeland_channel"])
        await set_mandatory_channel_enabled(session, True)

    await _seed_blocked_user(6002)

    call_count = 0

    async def _counting_get_chat_member(self: Bot, *, chat_id: str, user_id: int):
        nonlocal call_count
        call_count += 1
        raise AssertionError("get_chat_member must never be called for a blocked user")

    monkeypatch.setattr(Bot, "get_chat_member", _counting_get_chat_member)

    await dispatcher.feed_update(bot, make_message_update(6002, "/start"))

    assert call_count == 0
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert _BLOCKED_SNIPPET in sent[0][1]["text"]
