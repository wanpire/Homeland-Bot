from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiogram.types import Document, Update

from app.db.session import async_session_maker
from tests.factories import (
    FAKE_ADMIN_ID,
    make_callback_update,
    make_message,
    make_message_update,
    make_photo_message,
    make_photo_message_update,
    seed_bot_user,
)
from tests.fakes.fake_bot_session import FakeBotSession


async def _drain_background_tasks() -> None:
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks)


def _buttons(markup: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [b for row in (markup or {"inline_keyboard": []})["inline_keyboard"] for b in row]


def _last_screen(fake_session: FakeBotSession) -> tuple[str, dict[str, Any]]:
    screens = [c for c in fake_session.calls if c[0] in ("sendMessage", "editMessageText", "sendPhoto")]
    return screens[-1]


# --- Customer side: main-menu callback data tapped under a campaign photo ---


@pytest.mark.asyncio
async def test_menu_button_under_a_photo_sends_a_fresh_screen(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A campaign photo's button carries plain main-menu callback data.
    Telegram refuses editMessageText on a photo, so the section entry
    handler must send a new message instead of editing."""
    async with async_session_maker() as session:
        await seed_bot_user(session, 801, username="viewer")

    photo = make_photo_message(801, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(801, "menu:buy", anchor_message=photo))

    assert [c for c in fake_session.calls if c[0] == "editMessageText"] == []
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert sent and sent[-1][1]["chat_id"] == 801
    assert _buttons(sent[-1][1].get("reply_markup")), "buy category screen must carry its keyboard"


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["menu:renew", "menu:trial", "menu:myservices", "menu:support"])
async def test_every_campaign_section_works_under_a_photo(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    async with async_session_maker() as session:
        await seed_bot_user(session, 802, username="viewer2")

    photo = make_photo_message(802, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(802, data, anchor_message=photo))

    assert [c for c in fake_session.calls if c[0] == "editMessageText"] == []
    assert any(c[0] == "sendMessage" and c[1]["chat_id"] == 802 for c in fake_session.calls)


# --- Admin side: the campaign compose flow ---


async def _seed_recipients() -> None:
    from app.services.bot_users import set_language

    async with async_session_maker() as session:
        await seed_bot_user(session, 811, username="fa_user")
        await seed_bot_user(session, 812, username="en_user")
        await set_language(session, 811, "fa")
        await set_language(session, 812, "en")


async def _compose_text(dispatcher: Any, bot: Any, text: str = "Big sale!") -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, text))


async def _send(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:confirm"))
    await _drain_background_tasks()
    return [c for c in fake_session.calls if c[0] in ("sendMessage", "sendPhoto") and c[1]["chat_id"] in (811, 812)]


@pytest.mark.asyncio
async def test_non_full_admin_cannot_start_campaign(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=703, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(703, "adm:broadcast:campaign"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("campaign" in c[1].get("text", "").lower() for c in edited)
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[0][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_document_content_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"))
    fake_session.reset()
    doc_msg = make_message(FAKE_ADMIN_ID).model_copy(
        update={"document": Document(file_id="doc-1", file_unique_id="doc-1-u")}
    )
    await dispatcher.feed_update(bot, Update(update_id=999001, message=doc_msg))

    _, payload = _last_screen(fake_session)
    assert "photo or text" in payload["text"].lower()
    assert any("cancel" in b["text"].lower() for b in _buttons(payload.get("reply_markup")))


@pytest.mark.asyncio
async def test_preset_buy_button_is_localised_per_recipient(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:preset"))

    # Preview goes to the admin before the confirm prompt.
    admin_msgs = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == FAKE_ADMIN_ID]
    assert admin_msgs[0][1]["text"] == "Big sale!"
    assert _buttons(admin_msgs[0][1]["reply_markup"])[0]["callback_data"] == "menu:buy"
    assert "2 user" in admin_msgs[-1][1]["text"]

    delivered = await _send(dispatcher, bot, fake_session)
    by_chat = {c[1]["chat_id"]: _buttons(c[1]["reply_markup"])[0] for c in delivered}
    assert by_chat[811]["text"] == "🔑 خرید اشتراک" and by_chat[811]["callback_data"] == "menu:buy"
    assert by_chat[812]["text"] == "🔑 Buy Subscription" and by_chat[812]["callback_data"] == "menu:buy"
    summary = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == FAKE_ADMIN_ID]
    assert "campaign done" in summary[-1][1]["text"].lower() and "sent: 2" in summary[-1][1]["text"]


@pytest.mark.asyncio
async def test_other_menu_button_reuses_section_callback(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:menu"))
    _, chooser = _last_screen(fake_session)
    keys = {b["callback_data"] for b in _buttons(chooser["reply_markup"])}
    assert "adm:broadcast:campaign:btn:menu:renew" in keys
    assert "adm:broadcast:campaign:btn:menu:buy" not in keys  # buy is the preset

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:menu:renew"))
    delivered = await _send(dispatcher, bot, fake_session)
    by_chat = {c[1]["chat_id"]: _buttons(c[1]["reply_markup"])[0] for c in delivered}
    assert by_chat[811] == {"text": "♻️ تمدید سرویس", "callback_data": "menu:renew"}
    assert by_chat[812] == {"text": "♻️ Renew Service", "callback_data": "menu:renew"}


@pytest.mark.asyncio
async def test_custom_button_with_section_destination(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "  Try it free  "))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:trial"))

    delivered = await _send(dispatcher, bot, fake_session)
    assert len(delivered) == 2
    for c in delivered:
        assert _buttons(c[1]["reply_markup"])[0] == {"text": "Try it free", "callback_data": "menu:trial"}


@pytest.mark.asyncio
async def test_custom_button_with_url_destination(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_recipients()
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "Our site"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:url"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "https://homeland.example/promo"))

    delivered = await _send(dispatcher, bot, fake_session)
    assert len(delivered) == 2
    for c in delivered:
        btn = _buttons(c[1]["reply_markup"])[0]
        assert btn["text"] == "Our site" and btn["url"] == "https://homeland.example/promo"
        assert "callback_data" not in btn


@pytest.mark.asyncio
async def test_invalid_label_and_url_reprompt(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _compose_text(dispatcher, bot)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "x" * 65))
    assert "1–64" in _last_screen(fake_session)[1]["text"]

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ok label"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:url"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ftp://nope"))
    assert "valid" in _last_screen(fake_session)[1]["text"].lower()
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "https://ok.example"))
    assert "preview" in _last_screen(fake_session)[1]["text"].lower()


@pytest.mark.asyncio
async def test_no_button_photo_campaign(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _seed_recipients()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"))
    await dispatcher.feed_update(bot, make_photo_message_update(FAKE_ADMIN_ID, file_id="promo-photo"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:none"))

    delivered = await _send(dispatcher, bot, fake_session)
    assert len(delivered) == 2
    assert {c[0] for c in delivered} == {"sendPhoto"}
    assert all(c[1]["photo"] == "promo-photo" and "reply_markup" not in c[1] for c in delivered)


@pytest.mark.asyncio
async def test_every_campaign_screen_offers_back_or_cancel(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    for update in (
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign"),
        make_message_update(FAKE_ADMIN_ID, "Promo"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:menu"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:btn:custom"),
        make_message_update(FAKE_ADMIN_ID, "Label"),
        make_callback_update(FAKE_ADMIN_ID, "adm:broadcast:campaign:dest:url"),
        make_message_update(FAKE_ADMIN_ID, "https://ok.example"),
    ):
        fake_session.reset()
        await dispatcher.feed_update(bot, update)
        labels = [b["text"].lower() for b in _buttons(_last_screen(fake_session)[1].get("reply_markup"))]
        assert any("back" in label or "cancel" in label for label in labels), update
