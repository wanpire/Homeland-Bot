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
