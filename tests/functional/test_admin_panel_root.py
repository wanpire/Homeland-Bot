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


def _button_callbacks(fake_session: FakeBotSession) -> dict[str, str]:
    """Returns a mapping of button text to callback_data from the last editMessageText."""
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    markup = edited[-1][1]["reply_markup"]
    return {b["text"]: b["callback_data"] for row in markup["inline_keyboard"] for b in row}


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
    assert "👤 Users" in buttons
    assert "📚 Tutorials & Profiles" in buttons
    assert "🏷 Discount Codes" not in buttons
    assert "⚙️ Settings" not in buttons
    # Broadcast's router is gated IsFullAdmin, so a support admin must not
    # even see the button (spec §2) - a visible-but-filter-rejected button
    # gives zero feedback when tapped.
    assert "📢 Broadcast" not in buttons


@pytest.mark.asyncio
async def test_sales_admin_sees_discounts_but_not_settings(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_admin(602, "sales")

    await dispatcher.feed_update(bot, make_callback_update(602, "adm:root"))

    buttons = _buttons(fake_session)
    assert "🏷 Discount Codes" in buttons
    assert "⚙️ Settings" not in buttons
    assert "📢 Broadcast" not in buttons


@pytest.mark.asyncio
async def test_full_admin_sees_every_section(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:root"))

    buttons = _buttons(fake_session)
    assert "📢 Broadcast" in buttons
    assert "🏷 Discount Codes" in buttons
    assert "⚙️ Settings" in buttons


@pytest.mark.asyncio
async def test_unmatched_adm_callback_gets_a_permission_alert_not_silence(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A sales admin holding a stale keyboard (or any future filter-gated
    adm:* route) must get explicit feedback rather than an indefinite
    Telegram spinner - admin_fallback.router is the catch-all that
    guarantees answerCallbackQuery always fires."""
    await _seed_admin(605, "sales")

    await dispatcher.feed_update(bot, make_callback_update(605, "adm:broadcast"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert len(answered) == 1
    assert "permission" in answered[0][1]["text"].lower()
    assert answered[0][1].get("show_alert") is True
    assert [c for c in fake_session.calls if c[0] == "editMessageText"] == []


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


@pytest.mark.asyncio
async def test_adm_tutorials_back_button_targets_admin_root(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:tutorials"))

    callbacks = _button_callbacks(fake_session)
    assert "⬅️ Back to Admin Panel" in callbacks
    assert callbacks["⬅️ Back to Admin Panel"] == "adm:root"
