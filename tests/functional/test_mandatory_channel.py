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
async def test_recheck_tap_while_still_not_a_member_shows_alert_not_silence(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    await _enable_with_channels("homeland_channel")

    async def _fake_get_chat_member(self: Bot, *, chat_id: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(status="left")

    monkeypatch.setattr(Bot, "get_chat_member", _fake_get_chat_member)

    # First tap: shows the join prompt.
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))
    # Second tap ("I've Joined", still not actually a member): must not
    # crash, and must give the user visible feedback rather than a silent
    # swallowed exception.
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:root"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert len(answered) == 1
    assert "haven't joined" in answered[0][1].get("text", "").lower()
    assert answered[0][1].get("show_alert") is True


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
