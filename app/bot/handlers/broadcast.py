from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin import admin_root_menu
from app.bot.keyboards.broadcast import broadcast_compose_keyboard, broadcast_confirm_keyboard
from app.bot.states.broadcast import BroadcastStates
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.bot_users import list_bot_user_ids

router = Router(name="broadcast")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

logger = logging.getLogger(__name__)

_SEND_DELAY_SECONDS = 0.05
_COMPOSE_TEXT = "📢 Send the message to broadcast — text, a photo, or a document:"


@router.callback_query(F.data == "adm:broadcast")
async def broadcast_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.content)
    if callback.message is not None:
        await callback.message.edit_text(_COMPOSE_TEXT, reply_markup=broadcast_compose_keyboard())
    await callback.answer()


@router.message(BroadcastStates.content)
async def broadcast_receive_content_msg(message: Message, state: FSMContext) -> None:
    if message.photo:
        content: dict[str, Any] = {"kind": "photo", "file_id": message.photo[-1].file_id, "caption": message.caption or ""}
    elif message.document:
        content = {"kind": "document", "file_id": message.document.file_id, "caption": message.caption or ""}
    elif message.text:
        content = {"kind": "text", "text": message.text}
    else:
        await message.answer("⚠️ Send text, a photo, or a document.", reply_markup=broadcast_compose_keyboard())
        return

    await state.update_data(content=content)
    await state.set_state(BroadcastStates.confirm)

    async with async_session_maker() as session:
        recipient_count = len([tid for tid in await list_bot_user_ids(session) if tid != message.from_user.id])
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

    asyncio.create_task(_run_broadcast(callback.bot, callback.from_user.id, content))


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


async def _run_broadcast(bot: Bot, admin_telegram_id: int, content: dict[str, Any]) -> None:
    async with async_session_maker() as session:
        recipient_ids = [tid for tid in await list_bot_user_ids(session) if tid != admin_telegram_id]

    sent, failed = 0, 0
    for telegram_id in recipient_ids:
        try:
            if content["kind"] == "text":
                await bot.send_message(telegram_id, content["text"])
            elif content["kind"] == "photo":
                await bot.send_photo(telegram_id, content["file_id"], caption=content["caption"] or None)
            else:
                await bot.send_document(telegram_id, content["file_id"], caption=content["caption"] or None)
            sent += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(_SEND_DELAY_SECONDS)

    try:
        await bot.send_message(admin_telegram_id, f"✅ Broadcast done — sent: {sent}, failed: {failed}.")
    except TelegramAPIError:
        logger.exception("Could not deliver broadcast summary to admin telegram_id=%s", admin_telegram_id)
