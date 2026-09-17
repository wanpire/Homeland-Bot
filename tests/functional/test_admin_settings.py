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
async def test_channel_edit_rejects_channel_id_instead_of_username(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.mandatory_channel import get_mandatory_channels

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "-1001234567890"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("not a valid" in c[1].get("text", "").lower() for c in sent)

    async with async_session_maker() as session:
        assert await get_mandatory_channels(session) == []


@pytest.mark.asyncio
async def test_channel_edit_rejects_url_instead_of_username(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:channel:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "https://t.me/homeland_channel"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("not a valid" in c[1].get("text", "").lower() for c in sent)


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


@pytest.mark.asyncio
async def test_admin_settings_menu_includes_renewal_reminders_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "⏰ Renewal Reminders" in buttons


@pytest.mark.asyncio
async def test_reminders_status_shows_enabled_and_default_days_when_unset(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "enabled" in text.lower()
    assert "2 day" in text.lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "✏️ Edit Days Before" in buttons
    assert "🔴 Turn Off" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_non_full_admin_cannot_access_reminders_settings(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.admin_users import add_admin

    async with async_session_maker() as session:
        await add_admin(session, 611, "sales")

    await dispatcher.feed_update(bot, make_callback_update(611, "adm:settings:reminders"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_reminders_edit_sets_days_before(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "5"))

    async with async_session_maker() as session:
        assert await get_config(session, "reminder_days_before") == "5"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "updated" in sent[-1][1]["text"].lower()
    assert "5 day" in sent[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_reminders_edit_rejects_non_digit_input(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "abc"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("positive whole number" in c[1].get("text", "").lower() for c in sent)

    async with async_session_maker() as session:
        assert await get_config(session, "reminder_days_before") is None


@pytest.mark.asyncio
async def test_reminders_edit_rejects_zero(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:edit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "0"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("positive whole number" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_reminders_toggle_flips_state(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:toggle"))
    async with async_session_maker() as session:
        assert await get_config(session, "reminder_enabled") == "false"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🟢 Turn On" in buttons

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reminders:toggle"))
    async with async_session_maker() as session:
        assert await get_config(session, "reminder_enabled") == "true"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔴 Turn Off" in buttons
