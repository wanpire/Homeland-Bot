from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_new_user_sees_language_chooser_instead_of_main_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Undoes the autouse test-default fixture for this one test, to
    verify the real production gating behavior - a brand-new customer
    (language still unset) must see the chooser, not the main menu."""
    from app.services.bot_users import get_language
    import app.bot.middlewares.language as language_mw

    monkeypatch.setattr(language_mw, "get_language", get_language)

    await dispatcher.feed_update(bot, make_message_update(20001, "/start"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "Please choose your language" in sent[0][1]["text"]
    buttons = [b["text"] for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🇮🇷 فارسی" in buttons
    assert "🇬🇧 English" in buttons


@pytest.mark.asyncio
async def test_choosing_persian_sets_language_and_shows_persian_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.bot_users import get_language as real_get_language
    import app.bot.middlewares.language as language_mw

    monkeypatch.setattr(language_mw, "get_language", real_get_language)

    await dispatcher.feed_update(bot, make_message_update(20002, "/start"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(20002, "lang:set:fa"))

    async with async_session_maker() as session:
        assert await real_get_language(session, 20002) == "fa"

    # lang_set_cb edits the message to a "Language updated" confirmation,
    # then calls send_main_menu(), which - like start_cmd's and
    # fallback_to_main_menu's calls to the same helper - always sends a
    # FRESH message via Message.answer() (sendMessage), never an edit. So
    # the localized welcome text is asserted on sendMessage, not
    # editMessageText - matching send_main_menu's actual, interface-
    # documented behavior rather than the edit used for the transient
    # "language updated" confirmation immediately before it.
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("خوش آمدید" in c[1]["text"] for c in sent)


@pytest.mark.asyncio
async def test_choosing_english_sets_language_and_shows_english_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.bot_users import get_language as real_get_language
    import app.bot.middlewares.language as language_mw

    monkeypatch.setattr(language_mw, "get_language", real_get_language)

    await dispatcher.feed_update(bot, make_message_update(20003, "/start"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(20003, "lang:set:en"))

    async with async_session_maker() as session:
        assert await real_get_language(session, 20003) == "en"

    # See the comment in test_choosing_persian_sets_language_and_shows_persian_menu:
    # send_main_menu always sends a fresh message, not an edit.
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("Welcome to Homeland" in c[1]["text"] for c in sent)


@pytest.mark.asyncio
async def test_language_button_on_main_menu_reruns_chooser(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(20004, "menu:language"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Please choose your language" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_changing_language_later_updates_stored_value(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import get_language

    await dispatcher.feed_update(bot, make_callback_update(20005, "lang:set:fa"))
    await dispatcher.feed_update(bot, make_callback_update(20005, "menu:language"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(20005, "lang:set:en"))

    async with async_session_maker() as session:
        assert await get_language(session, 20005) == "en"
