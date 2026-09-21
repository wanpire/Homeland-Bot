from __future__ import annotations

from typing import Any

import pytest

from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_start_shows_english_main_menu(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(999, "/start")
    await dispatcher.feed_update(bot, update)

    sent = [call for call in fake_session.calls if call[0] == "sendMessage"]
    assert len(sent) == 1
    _, data = sent[0]
    assert "Welcome to Homeland" in data["text"]

    buttons = [btn["text"] for row in data["reply_markup"]["inline_keyboard"] for btn in row]
    assert buttons == [
        "🔑 Buy Subscription",
        "♻️ Renew Service",
        "🎁 Free Trial",
        "🛍 My Services",
        "📚 Tutorials",
        "☎️ Support",
        "🌐 Language",
    ]


@pytest.mark.asyncio
async def test_start_shows_admin_button_for_admin(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(FAKE_ADMIN_ID, "/start")
    await dispatcher.feed_update(bot, update)

    _, data = [call for call in fake_session.calls if call[0] == "sendMessage"][0]
    buttons = [btn["text"] for row in data["reply_markup"]["inline_keyboard"] for btn in row]
    assert "🛠 Admin Panel" in buttons


@pytest.mark.asyncio
async def test_menu_tutorials_opens_the_real_section(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    """Tutorials was a coming-soon placeholder until the section shipped -
    tapping it must now render the protocol picker, not an alert."""
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:tutorials"))

    answered = [call for call in fake_session.calls if call[0] == "answerCallbackQuery"]
    assert not any("coming soon" in (call[1].get("text") or "").lower() for call in answered)

    screens = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    buttons = [b["text"] for row in screens[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "OpenVPN" in buttons and "L2TP" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_menu_support_shows_configured_contact(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.session import async_session_maker
    from app.services.app_config import set_config

    async with async_session_maker() as session:
        await set_config(session, "support_username", "@homeland_support")

    update = make_callback_update(999, "menu:support")
    await dispatcher.feed_update(bot, update)

    edited = [call for call in fake_session.calls if call[0] == "editMessageText"]
    assert len(edited) == 1
    all_buttons = [btn for row in edited[0][1]["reply_markup"]["inline_keyboard"] for btn in row]
    support_button = next(b for b in all_buttons if "support" in b["text"].lower() and "back" not in b["text"].lower())
    assert support_button["url"] == "https://t.me/homeland_support"
    assert any("back" in b["text"].lower() for b in all_buttons)


@pytest.mark.asyncio
async def test_menu_support_falls_back_when_not_configured(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_callback_update(999, "menu:support")
    await dispatcher.feed_update(bot, update)

    edited = [call for call in fake_session.calls if call[0] == "editMessageText"]
    assert len(edited) == 1
    assert "isn't configured" in edited[0][1]["text"].lower()
    all_buttons = [btn for row in edited[0][1]["reply_markup"]["inline_keyboard"] for btn in row]
    assert len(all_buttons) == 1
    assert "back" in all_buttons[0]["text"].lower()


@pytest.mark.asyncio
async def test_menu_root_callback_redraws_main_menu(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_callback_update(999, "menu:root")
    await dispatcher.feed_update(bot, update)

    edited = [call for call in fake_session.calls if call[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Welcome to Homeland" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_unrecognized_message_falls_back_to_main_menu(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(999, "gibberish")
    await dispatcher.feed_update(bot, update)

    sent = [call for call in fake_session.calls if call[0] == "sendMessage"]
    assert len(sent) == 1
    assert "Welcome to Homeland" in sent[0][1]["text"]


@pytest.mark.asyncio
async def test_main_menu_includes_language_button(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(999, "/start")
    await dispatcher.feed_update(bot, update)

    _, data = [call for call in fake_session.calls if call[0] == "sendMessage"][0]
    buttons = [btn["text"] for row in data["reply_markup"]["inline_keyboard"] for btn in row]
    assert "🌐 Language" in buttons
