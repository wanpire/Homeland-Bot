from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import IsFullAdmin
from app.bot.keyboards.admin_settings import back_to_settings_keyboard, settings_edit_cancel_keyboard
from app.bot.states.admin_settings import EditSupportStates
from app.db.session import async_session_maker
from app.services.app_config import set_config
from app.services.groups import sync_groups
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError

router = Router(name="admin_settings")
router.message.filter(IsFullAdmin())
router.callback_query.filter(IsFullAdmin())

_SUPPORT_PROMPT_TEXT = "Send the support contact (e.g. @homeland_support):"
_EMPTY_SUPPORT_TEXT = "⚠️ Send a non-empty value."
_SYNC_FAILED_TEXT = "⚠️ Could not reach IBSng to sync groups. Please try again shortly."


@router.callback_query(F.data == "adm:settings:support")
async def settings_edit_support_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditSupportStates.support_username)
    if callback.message is not None:
        await callback.message.edit_text(_SUPPORT_PROMPT_TEXT, reply_markup=settings_edit_cancel_keyboard())
    await callback.answer()


@router.message(EditSupportStates.support_username)
async def settings_receive_support_username(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer(_EMPTY_SUPPORT_TEXT, reply_markup=settings_edit_cancel_keyboard())
        return
    async with async_session_maker() as session:
        await set_config(session, "support_username", value)
    await state.clear()
    await message.answer(f"✅ Support contact set to {value}.", reply_markup=back_to_settings_keyboard())


@router.callback_query(F.data == "adm:settings:syncgroups")
async def settings_sync_groups_cb(callback: CallbackQuery) -> None:
    try:
        async with async_session_maker() as session, IBSngClient() as client:
            groups = await sync_groups(session, client)
    except IBSngError:
        if callback.message is not None:
            await callback.message.edit_text(_SYNC_FAILED_TEXT, reply_markup=back_to_settings_keyboard())
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(
            f"🔄 Synced {len(groups)} Homeland group(s).", reply_markup=back_to_settings_keyboard()
        )
    await callback.answer()
