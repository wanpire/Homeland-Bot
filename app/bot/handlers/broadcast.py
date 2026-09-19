from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin import admin_root_menu
from app.bot.keyboards.broadcast import (
    broadcast_compose_keyboard,
    broadcast_confirm_keyboard,
    broadcast_submenu_keyboard,
)
from app.bot.states.broadcast import BroadcastStates
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.broadcast import list_recipients, start_broadcast_task

router = Router(name="broadcast")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

SUBMENU_TEXT = (
    "📢 <b>Broadcast</b>\n\n"
    "Announcement: a plain message to every user.\n"
    "Ad Campaign: a photo or text with an optional button."
)
_COMPOSE_TEXT = "📢 Send the message to broadcast — text, a photo, or a document:"


@router.callback_query(F.data == "adm:broadcast")
async def broadcast_submenu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(SUBMENU_TEXT, reply_markup=broadcast_submenu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm:broadcast:announce")
async def broadcast_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.content)
    if callback.message is not None:
        await callback.message.edit_text(_COMPOSE_TEXT, reply_markup=broadcast_compose_keyboard())
    await callback.answer()


@router.message(BroadcastStates.content)
async def broadcast_receive_content_msg(message: Message, state: FSMContext) -> None:
    # message.html_text re-renders the message's formatting entities as
    # HTML and correctly escapes any literal &/</> the admin typed - the
    # bot's default parse mode is HTML (app/main.py), and a raw,
    # unescaped message.text/message.caption containing one of those
    # characters makes Telegram reject the whole send as malformed HTML.
    # (When only a caption is set, message.text is None, so html_text
    # falls back to rendering message.caption/caption_entities - aiogram
    # has no separate html_caption property.)
    if message.photo:
        content: dict[str, Any] = {"kind": "photo", "file_id": message.photo[-1].file_id, "caption": message.html_text}
    elif message.document:
        content = {"kind": "document", "file_id": message.document.file_id, "caption": message.html_text}
    elif message.text:
        content = {"kind": "text", "text": message.html_text}
    else:
        await message.answer("⚠️ Send text, a photo, or a document.", reply_markup=broadcast_compose_keyboard())
        return

    await state.update_data(content=content)
    await state.set_state(BroadcastStates.confirm)

    async with async_session_maker() as session:
        recipient_count = len(await list_recipients(session, exclude_telegram_id=message.from_user.id))
    await message.answer(
        f"📢 Ready to broadcast to {recipient_count} user(s). Send it?",
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.callback_query(BroadcastStates.confirm, F.data == "adm:broadcast:confirm")
async def broadcast_confirm_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    content = data["content"]
    await state.clear()

    if callback.message is not None:
        await callback.message.edit_text("📤 Broadcast started — you'll get a summary when it's done.")
    await callback.answer()

    start_broadcast_task(callback.bot, callback.from_user.id, content)


@router.callback_query(F.data == "adm:broadcast:cancel")
async def broadcast_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        is_sales = await has_level(session, callback.from_user.id, "sales")
        is_full = await has_level(session, callback.from_user.id, "full")
    if callback.message is not None:
        await callback.message.edit_text(
            "🛠 <b>Admin Panel</b>", reply_markup=admin_root_menu(is_sales_admin=is_sales, is_full_admin=is_full)
        )
    await callback.answer()
