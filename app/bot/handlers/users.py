from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.menus import main_menu, support_keyboard
from app.config import get_settings
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.app_config import get_config
from app.services.trial_config import is_trial_enabled

router = Router(name="users")

WELCOME_TEXT = "👋 Welcome to Homeland VPN.\n\nChoose an option below:"
PLACEHOLDER_TEXT = "🚧 This feature is coming soon."
_SUPPORT_TEXT = "☎️ <b>Support</b>\n\nTap the button below to contact support."
_SUPPORT_NOT_CONFIGURED_TEXT = "☎️ Support contact isn't configured yet. Please check back soon."

_PLACEHOLDER_CALLBACKS = {
    "menu:tutorials",
}


async def _menu_flags(telegram_id: int) -> tuple[bool, bool]:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support"), await is_trial_enabled(session)


async def send_main_menu(target: Message) -> None:
    is_admin, trial_enabled = await _menu_flags(target.from_user.id) if target.from_user else (False, True)
    await target.answer(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin, trial_enabled=trial_enabled))


@router.message(Command("start"))
async def start_cmd(message: Message) -> None:
    await send_main_menu(message)


@router.callback_query(F.data == "menu:root")
async def menu_root_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        is_admin, trial_enabled = await _menu_flags(callback.from_user.id)
        await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin, trial_enabled=trial_enabled))
    await callback.answer()


@router.callback_query(F.data.in_(_PLACEHOLDER_CALLBACKS))
async def placeholder_cb(callback: CallbackQuery) -> None:
    await callback.answer(PLACEHOLDER_TEXT, show_alert=True)


@router.callback_query(F.data == "menu:support")
async def menu_support_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        support_username = await get_config(session, "support_username")
    if not support_username:
        support_username = get_settings().support_username

    url = f"https://t.me/{support_username.lstrip('@')}" if support_username else None
    text = _SUPPORT_TEXT if url else _SUPPORT_NOT_CONFIGURED_TEXT
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=support_keyboard(url))
    await callback.answer()
