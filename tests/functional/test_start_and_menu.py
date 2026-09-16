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
        "📚 Tutorial & Support",
    ]


@pytest.mark.asyncio
async def test_start_shows_admin_button_for_admin(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(FAKE_ADMIN_ID, "/start")
    await dispatcher.feed_update(bot, update)

    _, data = [call for call in fake_session.calls if call[0] == "sendMessage"][0]
    buttons = [btn["text"] for row in data["reply_markup"]["inline_keyboard"] for btn in row]
    assert "🛠 Admin Panel" in buttons


@pytest.mark.asyncio
async def test_placeholder_callbacks_answer_coming_soon(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    for callback_data in (
        "menu:buy",
        "menu:renew",
        "menu:myservices",
        "menu:tutorials",
    ):
        fake_session.reset()
        update = make_callback_update(999, callback_data)
        await dispatcher.feed_update(bot, update)

        answered = [call for call in fake_session.calls if call[0] == "answerCallbackQuery"]
        assert len(answered) == 1
        assert "coming soon" in answered[0][1]["text"].lower()


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
