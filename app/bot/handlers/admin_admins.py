from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin_admins import (
    add_admin_level_keyboard,
    add_admin_prompt_keyboard,
    admin_admins_list_keyboard,
    back_to_admins_keyboard,
    remove_admin_confirm_keyboard,
)
from app.bot.states.admin_admins import AddAdminStates
from app.config import get_settings
from app.db.models.bot_user import BotUser
from app.db.session import async_session_maker
from app.services.admin_users import LEVEL_LABELS, LEVELS, add_admin, get_admin, is_last_full_admin, list_admins, remove_admin

router = Router(name="admin_admins")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_LIST_TEXT_TEMPLATE = "👥 <b>Admins</b>\n\nℹ️ {count} bootstrap admin(s) — configured via ADMIN_IDS, always full access, not manageable here."
_ADD_PROMPT_TEXT = "Send the numeric Telegram ID to add as admin:"
_NOT_A_NUMBER_TEXT = "⚠️ Send a numeric Telegram ID."
_ALREADY_BOOTSTRAP_TEXT = "⚠️ That Telegram ID is already a bootstrap admin (via ADMIN_IDS)."
_ALREADY_DB_ADMIN_TEXT = "⚠️ That Telegram ID is already an admin — remove them first if you want to change their level."
_LEVEL_PROMPT_TEXT = "Pick a level:"
_LAST_FULL_ADMIN_TEXT = "⚠️ Can't remove the last full admin — this would lock everyone out."


async def _display_name(session, telegram_id: int) -> str:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is not None and row.username:
        return f"@{row.username}"
    return str(telegram_id)


async def _render_list(session) -> tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    admins = await list_admins(session)
    rows = [(admin, await _display_name(session, admin.telegram_id)) for admin in admins]
    text = _LIST_TEXT_TEMPLATE.format(count=len(settings.admin_id_list))
    return text, admin_admins_list_keyboard(rows)


@router.callback_query(F.data == "adm:admins")
async def admin_admins_list_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session:
        text, keyboard = await _render_list(session)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "adm:admins:add")
async def admin_add_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddAdminStates.telegram_id)
    if callback.message is not None:
        await callback.message.edit_text(_ADD_PROMPT_TEXT, reply_markup=add_admin_prompt_keyboard())
    await callback.answer()


@router.message(AddAdminStates.telegram_id)
async def admin_add_receive_id(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(_NOT_A_NUMBER_TEXT, reply_markup=add_admin_prompt_keyboard())
        return
    telegram_id = int(raw)

    settings = get_settings()
    if telegram_id in settings.admin_id_list:
        await message.answer(_ALREADY_BOOTSTRAP_TEXT, reply_markup=add_admin_prompt_keyboard())
        return

    async with async_session_maker() as session:
        if await get_admin(session, telegram_id) is not None:
            await message.answer(_ALREADY_DB_ADMIN_TEXT, reply_markup=add_admin_prompt_keyboard())
            return

    await state.update_data(new_admin_telegram_id=telegram_id)
    await state.set_state(AddAdminStates.level)
    await message.answer(_LEVEL_PROMPT_TEXT, reply_markup=add_admin_level_keyboard())


@router.callback_query(AddAdminStates.level, F.data.startswith("adm:admins:add:level:"))
async def admin_add_receive_level(callback: CallbackQuery, state: FSMContext) -> None:
    level = callback.data.split(":")[-1]
    if level not in LEVELS:
        await callback.answer()
        return
    data = await state.get_data()
    telegram_id = data.get("new_admin_telegram_id")
    await state.clear()
    if telegram_id is None:
        await callback.answer()
        return

    async with async_session_maker() as session:
        await add_admin(session, telegram_id, level)
        text, keyboard = await _render_list(session)

    if callback.message is not None:
        await callback.message.edit_text(
            f"✅ Added {telegram_id} as {LEVEL_LABELS[level]}.\n\n{text}", reply_markup=keyboard
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:admins:remove:confirm:"))
async def admin_remove_confirm_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    telegram_id = int(callback.data.split(":")[-1])

    async with async_session_maker() as session:
        admin = await get_admin(session, telegram_id)
        if admin is not None and admin.level == "full" and await is_last_full_admin(session, telegram_id):
            if callback.message is not None:
                await callback.message.edit_text(_LAST_FULL_ADMIN_TEXT, reply_markup=back_to_admins_keyboard())
            await callback.answer()
            return

        await remove_admin(session, telegram_id)
        text, keyboard = await _render_list(session)

    if callback.message is not None:
        await callback.message.edit_text(f"✅ Removed {telegram_id}.\n\n{text}", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:admins:remove:"))
async def admin_remove_start_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    telegram_id = int(callback.data.split(":")[-1])
    if callback.message is not None:
        await callback.message.edit_text(
            f"Remove admin {telegram_id}? This cannot be undone.", reply_markup=remove_admin_confirm_keyboard(telegram_id)
        )
    await callback.answer()
