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
async def test_support_contact_with_html_special_chars_is_escaped_in_confirmation(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """The bot's default parse mode is HTML - a support contact value
    containing a raw &, <, or > must be escaped before it's interpolated
    into the confirmation message, or the send would break (and, short
    of that, render wrong)."""
    from app.services.app_config import get_config

    raw_value = "support@homeland <urgent> & co"
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:support"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, raw_value))

    async with async_session_maker() as session:
        assert await get_config(session, "support_username") == raw_value

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    confirmation = sent[-1][1]["text"]
    assert "support@homeland &lt;urgent&gt; &amp; co" in confirmation
    assert "<urgent>" not in confirmation
    assert " & co" not in confirmation


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
