from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import CHOOSE_LANGUAGE_TEXT


def language_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇮🇷 فارسی", callback_data="lang:set:fa")
    builder.button(text="🇬🇧 English", callback_data="lang:set:en")
    builder.adjust(2)
    return builder.as_markup()


async def show_language_chooser(callback: CallbackQuery) -> None:
    """Render the language chooser onto a callback's anchor message by
    editing it in place, if possible. Shared by LanguageMiddleware's
    gating branch and users.py's menu_language_cb - both used to carry
    their own unguarded edit_text call, which raised TelegramBadRequest
    (and left the customer with zero feedback) whenever the anchor message
    was too old to edit or already showed this exact content. Mirrors
    MandatoryChannelMiddleware's identical guard for the identical
    situation. The caller is still responsible for calling
    callback.answer() afterward."""
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(CHOOSE_LANGUAGE_TEXT, reply_markup=language_choice_keyboard())
        except TelegramBadRequest:
            pass  # identical content, or a stale/deleted/InaccessibleMessage
