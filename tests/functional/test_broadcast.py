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
