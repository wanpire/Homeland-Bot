from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.keyboards.admin import (
    admin_financial_menu,
    admin_root_menu,
    admin_settings_menu,
    admin_users_menu,
    back_to_admin_root_keyboard,
)
from app.bot.keyboards.tutorial_admin import tutorial_admin_root_keyboard
from app.bot.handlers.admin_fallback import NO_PERMISSION_TEXT
from app.db.session import async_session_maker
from app.services.admin_users import has_level

router = Router(name="admin")

_ROOT_TEXT = "🛠 <b>Admin Panel</b>"
_USERS_TEXT = "👤 <b>Users</b>"
_SETTINGS_TEXT = "⚙️ <b>System</b>"
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


_FINANCIAL_TEXT = "💰 <b>Financial</b>"
_REPORTS_TEXT = (
    "📊 <b>Reports</b>\n\n"
    "Signups, active vs expired accounts, revenue, trial conversion and "
    "top plans by sales arrive in Part 4 of the admin epic."
)
@router.callback_query(F.data == "adm:fin")
async def admin_financial_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "sales"):
            # Said out loud rather than silently dropped: this handler
            # consumes the callback, so admin_fallback never gets the
            # chance to show its alert, and a stale keyboard would
            # otherwise just spin with no explanation.
            await callback.answer(NO_PERMISSION_TEXT, show_alert=True)
            return
        is_full = await has_level(session, callback.from_user.id, "full")
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(
            _FINANCIAL_TEXT, reply_markup=admin_financial_menu(is_full_admin=is_full)
        )
    await callback.answer()


@router.callback_query(F.data == "adm:reports")
async def admin_reports_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "sales"):
            await callback.answer(NO_PERMISSION_TEXT, show_alert=True)
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_REPORTS_TEXT, reply_markup=back_to_admin_root_keyboard())
    await callback.answer()
