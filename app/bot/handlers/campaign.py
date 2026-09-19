"""Admin Ad Campaign flow: photo/text + optional single button, delivered
through app/services/broadcast.py exactly like an announcement. Admin
copy is English-only; only the delivered button label is localised."""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.campaign import (
    BACK_TO_BUTTON_CB,
    CAMPAIGN_SECTIONS,
    CONFIRM_CB,
    CUSTOM_CB,
    Button,
    campaign_back_cancel_keyboard,
    campaign_button_choice_keyboard,
    campaign_confirm_keyboard,
    campaign_content_keyboard,
    campaign_custom_dest_keyboard,
    campaign_keyboard,
    campaign_section_keyboard,
)
from app.bot.states.campaign import CampaignStates
from app.db.session import async_session_maker
from app.services.broadcast import list_recipients, start_broadcast_task

router = Router(name="campaign")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_CONTENT_TEXT = "🎯 <b>Ad Campaign</b>\n\nSend the campaign content — a photo (with optional caption) or text:"
_CONTENT_REJECT_TEXT = "⚠️ Send a photo or text."
_BUTTON_TEXT = "🎯 Add a button under the message?"
_SECTION_TEXT = "📋 Which main-menu button?"
_LABEL_TEXT = "✏️ Send the button label (1–64 characters):"
_LABEL_REJECT_TEXT = "⚠️ Label must be 1–64 characters."
_DEST_TEXT = "✏️ Where should the button go?"
_URL_TEXT = "🔗 Send the URL (http://, https:// or tg://):"
_URL_REJECT_TEXT = "⚠️ Send a valid http(s):// or tg:// URL."
_STARTED_TEXT = "📤 Campaign started — you'll get a summary when it's done."

_LABEL_MAX = 64
_URL_MAX = 1024
_URL_SCHEMES = ("http://", "https://", "tg://")


def _valid_url(value: str) -> bool:
    return value.startswith(_URL_SCHEMES) and len(value) <= _URL_MAX and not any(ch.isspace() for ch in value)


@router.callback_query(F.data == "adm:broadcast:campaign")
async def campaign_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CampaignStates.content)
    if callback.message is not None:
        await callback.message.edit_text(_CONTENT_TEXT, reply_markup=campaign_content_keyboard())
    await callback.answer()


@router.message(CampaignStates.content)
async def campaign_content_msg(message: Message, state: FSMContext) -> None:
    # html_text keeps the admin's formatting and escapes literal &/</> -
    # see app/bot/handlers/broadcast.py for the full reasoning.
    if message.photo:
        content: dict[str, Any] = {"kind": "photo", "file_id": message.photo[-1].file_id, "caption": message.html_text}
    elif message.text:
        content = {"kind": "text", "text": message.html_text}
    else:
        await message.answer(_CONTENT_REJECT_TEXT, reply_markup=campaign_content_keyboard())
        return
    await state.update_data(content=content, button=None)
    await state.set_state(CampaignStates.button_choice)
    await message.answer(_BUTTON_TEXT, reply_markup=campaign_button_choice_keyboard())


@router.callback_query(F.data == BACK_TO_BUTTON_CB)
async def campaign_button_choice_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if "content" not in await state.get_data():
        # Stale keyboard from a finished/cancelled campaign - restart.
        await campaign_start_cb(callback, state)
        return
    await state.set_state(CampaignStates.button_choice)
    if callback.message is not None:
        await callback.message.edit_text(_BUTTON_TEXT, reply_markup=campaign_button_choice_keyboard())
    await callback.answer()


@router.callback_query(CampaignStates.button_choice, F.data == "adm:broadcast:campaign:btn:preset")
async def campaign_preset_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await _go_to_preview(callback, state, lang, {"kind": "menu", "key": "buy"})


@router.callback_query(CampaignStates.button_choice, F.data == "adm:broadcast:campaign:btn:none")
async def campaign_none_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await _go_to_preview(callback, state, lang, None)


@router.callback_query(CampaignStates.button_choice, F.data == "adm:broadcast:campaign:btn:menu")
async def campaign_menu_list_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(
            _SECTION_TEXT, reply_markup=campaign_section_keyboard("adm:broadcast:campaign:btn:menu", exclude=("buy",))
        )
    await callback.answer()


@router.callback_query(CampaignStates.button_choice, F.data.startswith("adm:broadcast:campaign:btn:menu:"))
async def campaign_menu_pick_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    key = callback.data.split(":")[-1]
    if key not in CAMPAIGN_SECTIONS:
        await callback.answer()
        return
    await _go_to_preview(callback, state, lang, {"kind": "menu", "key": key})


@router.callback_query(F.data == CUSTOM_CB)
async def campaign_custom_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if "content" not in await state.get_data():
        await campaign_start_cb(callback, state)
        return
    await state.set_state(CampaignStates.custom_label)
    if callback.message is not None:
        await callback.message.edit_text(_LABEL_TEXT, reply_markup=campaign_back_cancel_keyboard(BACK_TO_BUTTON_CB))
    await callback.answer()


@router.message(CampaignStates.custom_label)
async def campaign_label_msg(message: Message, state: FSMContext) -> None:
    label = (message.text or "").strip()
    if not 1 <= len(label) <= _LABEL_MAX:
        await message.answer(_LABEL_REJECT_TEXT, reply_markup=campaign_back_cancel_keyboard(BACK_TO_BUTTON_CB))
        return
    await state.update_data(custom_label=label)
    await state.set_state(CampaignStates.custom_dest)
    await message.answer(_DEST_TEXT, reply_markup=campaign_custom_dest_keyboard())


@router.callback_query(CampaignStates.custom_dest, F.data == "adm:broadcast:campaign:dest:url")
async def campaign_dest_url_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CampaignStates.custom_url)
    if callback.message is not None:
        await callback.message.edit_text(_URL_TEXT, reply_markup=campaign_back_cancel_keyboard(CUSTOM_CB))
    await callback.answer()


@router.callback_query(CampaignStates.custom_dest, F.data.startswith("adm:broadcast:campaign:dest:"))
async def campaign_dest_section_cb(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    key = callback.data.split(":")[-1]
    if key not in CAMPAIGN_SECTIONS:
        await callback.answer()
        return
    data = await state.get_data()
    button: Button = {"kind": "custom", "label": data["custom_label"], "dest": {"kind": "menu", "key": key}}
    await _go_to_preview(callback, state, lang, button)


@router.message(CampaignStates.custom_url)
async def campaign_url_msg(message: Message, state: FSMContext, lang: str) -> None:
    url = (message.text or "").strip()
    if not _valid_url(url):
        await message.answer(_URL_REJECT_TEXT, reply_markup=campaign_back_cancel_keyboard(CUSTOM_CB))
        return
    data = await state.get_data()
    button: Button = {"kind": "custom", "label": data["custom_label"], "dest": {"kind": "url", "url": url}}
    await _send_preview(message, state, lang, button)


async def _go_to_preview(callback: CallbackQuery, state: FSMContext, lang: str, button: Button) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _send_preview(callback.message, state, lang, button)


async def _send_preview(target: Message, state: FSMContext, lang: str, button: Button) -> None:
    """Send the admin the real campaign message with the real keyboard (so
    the button can be tapped and verified), then the Send/Back/Cancel
    prompt. `target` is any message in the admin's private chat (the
    bot's own or the admin's) - only its chat is used, and in a private
    chat the chat id IS the admin's telegram id, so the recipient count
    excludes exactly whom run_broadcast will exclude."""
    data = await state.get_data()
    content = data["content"]
    await state.update_data(button=button)
    await state.set_state(CampaignStates.confirm)

    markup = campaign_keyboard(button, lang)
    if content["kind"] == "photo":
        await target.answer_photo(content["file_id"], caption=content["caption"] or None, reply_markup=markup)
    else:
        await target.answer(content["text"], reply_markup=markup)

    async with async_session_maker() as session:
        recipient_count = len(await list_recipients(session, exclude_telegram_id=target.chat.id))
    await target.answer(
        f"🎯 Campaign preview above. Send it to {recipient_count} user(s)?", reply_markup=campaign_confirm_keyboard()
    )


@router.callback_query(CampaignStates.confirm, F.data == CONFIRM_CB)
async def campaign_confirm_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    content, button = data["content"], data.get("button")
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_STARTED_TEXT)
    await callback.answer()
    start_broadcast_task(
        callback.bot,
        callback.from_user.id,
        content,
        keyboard_for=lambda lang: campaign_keyboard(button, lang),
        summary_label="Campaign",
    )
