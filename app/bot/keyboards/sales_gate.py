from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


def sales_paused_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("back_to_main_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
