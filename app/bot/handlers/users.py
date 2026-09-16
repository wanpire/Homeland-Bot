from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.menus import main_menu
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.app_config import get_config

router = Router(name="users")

WELCOME_TEXT = "👋 Welcome to Homeland VPN.\n\nChoose an option below:"
PLACEHOLDER_TEXT = "🚧 This feature is coming soon."
_SUPPORT_NOT_CONFIGURED_TEXT = "☎️ Support contact isn't configured yet. Please check back soon."

_PLACEHOLDER_CALLBACKS = {
    "menu:buy",
    "menu:renew",
    "menu:myservices",
    "menu:tutorials",
}


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


async def send_main_menu(target: Message) -> None:
    is_admin = await _is_admin(target.from_user.id) if target.from_user else False
    await target.answer(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin))


@router.message(Command("start"))
async def start_cmd(message: Message) -> None:
    await send_main_menu(message)


@router.callback_query(F.data == "menu:root")
async def menu_root_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        is_admin = await _is_admin(callback.from_user.id)
        await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin))
    await callback.answer()


@router.callback_query(F.data.in_(_PLACEHOLDER_CALLBACKS))
async def placeholder_cb(callback: CallbackQuery) -> None:
    await callback.answer(PLACEHOLDER_TEXT, show_alert=True)


@router.callback_query(F.data == "menu:support")
async def menu_support_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        support_username = await get_config(session, "support_username")
    text = (
        f"☎️ Contact support: {html.escape(support_username)}" if support_username else _SUPPORT_NOT_CONFIGURED_TEXT
    )
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard())
    await callback.answer()
