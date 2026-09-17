from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update, seed_bot_user
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_get_admin_returns_none_for_unknown_id() -> None:
    from app.services.admin_users import get_admin

    async with async_session_maker() as session:
        assert await get_admin(session, 999999) is None


@pytest.mark.asyncio
async def test_add_admin_creates_row_at_given_level() -> None:
    from app.services.admin_users import add_admin, get_admin

    async with async_session_maker() as session:
        await add_admin(session, 501, "sales")

    async with async_session_maker() as session:
        admin = await get_admin(session, 501)
    assert admin is not None
    assert admin.level == "sales"


@pytest.mark.asyncio
async def test_remove_admin_deletes_row() -> None:
    from app.services.admin_users import add_admin, get_admin, remove_admin

    async with async_session_maker() as session:
        await add_admin(session, 502, "support")

    async with async_session_maker() as session:
        await remove_admin(session, 502)

    async with async_session_maker() as session:
        assert await get_admin(session, 502) is None


@pytest.mark.asyncio
async def test_is_last_full_admin_false_when_bootstrap_admin_exists() -> None:
    from app.services.admin_users import add_admin, is_last_full_admin

    async with async_session_maker() as session:
        await add_admin(session, 503, "full")

    async with async_session_maker() as session:
        # FAKE_ADMIN_ID is a bootstrap admin (ADMIN_IDS), so removing the
        # only DB "full" row never actually locks anyone out.
        assert await is_last_full_admin(session, 503) is False


@pytest.mark.asyncio
async def test_is_last_full_admin_true_with_no_bootstrap_and_only_one_db_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.services.admin_users import add_admin, is_last_full_admin

    monkeypatch.setattr(get_settings(), "admin_ids", "")

    async with async_session_maker() as session:
        await add_admin(session, 504, "full")

    async with async_session_maker() as session:
        assert await is_last_full_admin(session, 504) is True


@pytest.mark.asyncio
async def test_is_last_full_admin_false_when_another_db_full_admin_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.services.admin_users import add_admin, is_last_full_admin

    monkeypatch.setattr(get_settings(), "admin_ids", "")

    async with async_session_maker() as session:
        await add_admin(session, 505, "full")
        await add_admin(session, 506, "full")

    async with async_session_maker() as session:
        assert await is_last_full_admin(session, 505) is False


@pytest.mark.asyncio
async def test_non_full_admin_cannot_access_admins_list(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.admin_users import add_admin

    async with async_session_maker() as session:
        await add_admin(session, 507, "sales")

    await dispatcher.feed_update(bot, make_callback_update(507, "adm:admins"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_admins_list_shows_bootstrap_note_and_db_admins(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.admin_users import add_admin

    async with async_session_maker() as session:
        await seed_bot_user(session, 508, username="salesperson")
        await add_admin(session, 508, "sales")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[-1][1]["text"]
    assert "bootstrap admin" in text.lower()
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("salesperson" in b and "Sales" in b for b in buttons)
    assert "➕ Add Admin" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_admin_root_menu_hides_manage_admins_for_non_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.admin_users import add_admin

    async with async_session_maker() as session:
        await add_admin(session, 509, "support")

    await dispatcher.feed_update(bot, make_callback_update(509, "adm:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "👥 Manage Admins" not in buttons


@pytest.mark.asyncio
async def test_admin_root_menu_shows_manage_admins_for_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "👥 Manage Admins" in buttons


@pytest.mark.asyncio
async def test_add_admin_flow_creates_admin_at_selected_level(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.admin_users import get_admin

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:add"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "510"))

    edited_or_sent = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    buttons = [b["text"] for row in edited_or_sent[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "Support" in buttons
    assert "Sales" in buttons
    assert "Full" in buttons

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:add:level:sales"))

    async with async_session_maker() as session:
        admin = await get_admin(session, 510)
    assert admin is not None
    assert admin.level == "sales"


@pytest.mark.asyncio
async def test_add_admin_rejects_non_numeric_id(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:add"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "not-a-number"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("numeric" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_add_admin_rejects_existing_bootstrap_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:add"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, str(FAKE_ADMIN_ID)))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("already" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_add_admin_rejects_existing_db_admin(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.admin_users import add_admin

    async with async_session_maker() as session:
        await add_admin(session, 511, "support")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:add"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "511"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("already" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_remove_admin_shows_confirm_then_deletes(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.admin_users import add_admin, get_admin

    async with async_session_maker() as session:
        await add_admin(session, 512, "support")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:remove:512"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "remove" in edited[-1][1]["text"].lower()
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("yes" in b.lower() for b in buttons)

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:remove:confirm:512"))

    async with async_session_maker() as session:
        assert await get_admin(session, 512) is None


@pytest.mark.asyncio
async def test_remove_admin_blocks_removing_last_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings
    from app.services.admin_users import add_admin, get_admin

    monkeypatch.setattr(get_settings(), "admin_ids", "")

    async with async_session_maker() as session:
        await add_admin(session, FAKE_ADMIN_ID, "full")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:admins:remove:confirm:{}".format(FAKE_ADMIN_ID)))

    async with async_session_maker() as session:
        assert await get_admin(session, FAKE_ADMIN_ID) is not None

    sent_or_edited = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    assert any("last full admin" in c[1].get("text", "").lower() or "lock" in c[1].get("text", "").lower() for c in sent_or_edited)
