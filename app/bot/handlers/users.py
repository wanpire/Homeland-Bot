from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.language import show_language_chooser
from app.bot.keyboards.menus import main_menu, support_keyboard
from app.config import get_settings
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.admin_users import has_level
from app.services.app_config import get_config
from app.services.bot_users import set_language

router = Router(name="users")

_PLACEHOLDER_CALLBACKS = {
    "menu:tutorials",
}


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


async def send_main_menu(target: Message, *, lang: str) -> None:
    is_admin = await _is_admin(target.from_user.id) if target.from_user else False
    await target.answer(t("welcome", lang), reply_markup=main_menu(is_admin=is_admin, lang=lang))


@router.message(Command("start"))
async def start_cmd(message: Message, lang: str) -> None:
    await send_main_menu(message, lang=lang)


@router.callback_query(F.data == "menu:root")
async def menu_root_cb(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        is_admin = await _is_admin(callback.from_user.id)
        await callback.message.edit_text(t("welcome", lang), reply_markup=main_menu(is_admin=is_admin, lang=lang))
    await callback.answer()


@router.callback_query(F.data.in_(_PLACEHOLDER_CALLBACKS))
async def placeholder_cb(callback: CallbackQuery, lang: str) -> None:
    await callback.answer(t("placeholder_coming_soon", lang), show_alert=True)


@router.callback_query(F.data == "menu:support")
async def menu_support_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        support_username = await get_config(session, "support_username")
    if not support_username:
        support_username = get_settings().support_username

    url = f"https://t.me/{support_username.lstrip('@')}" if support_username else None
    text = t("support_heading", lang) if url else t("support_not_configured", lang)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=support_keyboard(url, lang))
    await callback.answer()


@router.callback_query(F.data == "menu:language")
async def menu_language_cb(callback: CallbackQuery) -> None:
    await show_language_chooser(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("lang:set:"))
async def lang_set_cb(callback: CallbackQuery) -> None:
    lang = callback.data.split(":")[-1]
    if lang not in ("fa", "en"):
        lang = "en"
    async with async_session_maker() as session:
        await set_language(session, callback.from_user.id, lang)
    if callback.message is not None:
        await callback.message.edit_text(t("language_updated", lang))
        # Deliberately not routed through send_main_menu(callback.message,
        # ...): callback.message is the BOT's own message being edited, so
        # its from_user is the bot, not the customer - send_main_menu's
        # is_admin lookup would key off the bot's id and always resolve to
        # False. Derive is_admin from the real user (callback.from_user)
        # instead.
        is_admin = await _is_admin(callback.from_user.id)
        await callback.message.answer(t("welcome", lang), reply_markup=main_menu(is_admin=is_admin, lang=lang))
    await callback.answer()
