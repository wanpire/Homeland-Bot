from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.keyboards.admin import admin_root_menu, admin_settings_menu, admin_users_menu
from app.bot.keyboards.tutorial_admin import tutorial_admin_root_keyboard
from app.db.session import async_session_maker
from app.services.admin_users import has_level

router = Router(name="admin")

_ROOT_TEXT = "🛠 <b>Admin Panel</b>"
_USERS_TEXT = "👤 <b>Users</b>"
_SETTINGS_TEXT = "⚙️ <b>Settings</b>"
_TUTORIALS_TEXT = "📚 Tutorials & Profiles admin:"


@router.callback_query(F.data == "adm:root")
async def admin_root_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "support"):
            await callback.answer()
            return
        is_sales = await has_level(session, callback.from_user.id, "sales")
        is_full = await has_level(session, callback.from_user.id, "full")
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(
            _ROOT_TEXT, reply_markup=admin_root_menu(is_sales_admin=is_sales, is_full_admin=is_full)
        )
    await callback.answer()


@router.callback_query(F.data == "adm:users")
async def admin_users_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "support"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_USERS_TEXT, reply_markup=admin_users_menu())
    await callback.answer()


@router.callback_query(F.data == "adm:settings")
async def admin_settings_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "full"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_SETTINGS_TEXT, reply_markup=admin_settings_menu())
    await callback.answer()


@router.callback_query(F.data == "adm:tutorials")
async def admin_tutorials_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "support"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_TUTORIALS_TEXT, reply_markup=tutorial_admin_root_keyboard())
    await callback.answer()
