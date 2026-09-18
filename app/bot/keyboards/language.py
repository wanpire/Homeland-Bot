from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def language_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇮🇷 فارسی", callback_data="lang:set:fa")
    builder.button(text="🇬🇧 English", callback_data="lang:set:en")
    builder.adjust(2)
    return builder.as_markup()
