from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.menus import main_menu
from app.db.session import async_session_maker
from app.services.admin_users import has_level

router = Router(name="users")

WELCOME_TEXT = "👋 Welcome to Homeland VPN.\n\nChoose an option below:"
PLACEHOLDER_TEXT = "🚧 This feature is coming soon."

_PLACEHOLDER_CALLBACKS = {
    "menu:buy",
    "menu:renew",
    "menu:trial",
    "menu:myservices",
    "menu:tutorials",
    "adm:root",
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
