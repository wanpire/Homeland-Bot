from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message, make_message_update
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
async def test_chooser_gating_survives_an_uneditable_anchor_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: LanguageMiddleware's CallbackQuery gating branch used
    to call inner.message.edit_text(...) with no guard. Since there's no
    backfill, EVERY existing customer has language IS NULL and hits this
    branch on their very next interaction - if that happens to be a tap on
    a button from a message too old to edit (comes back as
    InaccessibleMessage, or any edit Telegram otherwise refuses), edit_text
    raises TelegramBadRequest and inner.answer() is never reached: zero
    feedback, a hanging spinner. Mirrors test_mandatory_channel.py's
    general approach (monkeypatch the relevant Telegram API call to raise
    TelegramBadRequest) - adapted to the session level here since
    Message.edit_text() routes through the bot's session rather than a
    plain Bot method (see the comment below).

    Against the pre-fix code this test doesn't just fail an assertion - the
    unguarded edit_text raises straight out of dispatcher.feed_update(),
    since handle_pool_timeout only claims pool-timeout errors and lets
    everything else (including TelegramBadRequest) propagate."""
    from aiogram.exceptions import TelegramBadRequest

    from app.services.bot_users import get_language as real_get_language
    import app.bot.middlewares.language as language_mw

    monkeypatch.setattr(language_mw, "get_language", real_get_language)

    # Message.edit_text() doesn't call a plain Bot.edit_message_text
    # method - it builds an EditMessageText call object and sends it
    # through the bot's session, which is FakeBotSession here. So the
    # raise has to come from the session's make_request, not from
    # patching a Bot method (that pattern only works for calls made
    # directly against a Bot method, like MandatoryChannelMiddleware's
    # get_chat_member).
    original_make_request = fake_session.make_request

    async def _make_request_raising_on_edit(bot: Any, method: Any, timeout: int | None = None) -> Any:
        if method.__api_method__ == "editMessageText":
            raise TelegramBadRequest(method=method, message="message to edit not found")
        return await original_make_request(bot, method, timeout)

    monkeypatch.setattr(fake_session, "make_request", _make_request_raising_on_edit)

    # A brand-new telegram_id (language unset) tapping any ordinary button -
    # exactly the shape LanguageMiddleware intercepts before the handler runs.
    await dispatcher.feed_update(bot, make_callback_update(20099, "menu:root"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []  # the monkeypatched Bot method always raised
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert len(answered) == 1


@pytest.mark.asyncio
async def test_language_button_on_main_menu_reruns_chooser(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(20004, "menu:language"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Please choose your language" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_admin_keeps_admin_panel_button_after_switching_language(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Regression test: lang_set_cb used to render the post-switch menu via
    send_main_menu(callback.message, lang=lang), which derives is_admin from
    callback.message.from_user - in production that's the BOT's own identity
    (the message being edited), not the customer, so an admin switching
    language lost the Admin Panel button until their next /start.

    The anchor message here is built with a non-admin from_user (simulating
    the bot-authored-message shape production actually has), independent of
    the callback's own from_user (FAKE_ADMIN_ID, the real tapping user) -
    make_callback_update's `telegram_id` only drives the anchor's from_user
    when no anchor_message is passed explicitly, so this reproduces the
    exact shape the bug depends on. Under the old code this would resolve
    is_admin against the anchor's from_user (not an admin) and drop the
    button; the fix derives is_admin from callback.from_user instead."""
    bot_authored_anchor = make_message(987654321, "(anchor)", username="HomelandVPNBot")

    await dispatcher.feed_update(
        bot, make_callback_update(FAKE_ADMIN_ID, "lang:set:en", anchor_message=bot_authored_anchor)
    )

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    buttons = [b["text"] for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🛠 Admin Panel" in buttons


@pytest.mark.asyncio
async def test_changing_language_later_updates_stored_value(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import get_language

    await dispatcher.feed_update(bot, make_callback_update(20005, "lang:set:fa"))
    await dispatcher.feed_update(bot, make_callback_update(20005, "menu:language"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(20005, "lang:set:en"))

    async with async_session_maker() as session:
        assert await get_language(session, 20005) == "en"
