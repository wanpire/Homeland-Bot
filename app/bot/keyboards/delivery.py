"""The keyboard under a delivered order.

Both destinations are the main menu's own callbacks: a buyer who has
just received credentials needs the setup guides next, so the message
leads straight into Tutorials rather than into a flow of its own."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


def order_delivered_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("tutorial_button", lang), callback_data="menu:tutorials")
    builder.button(text=t("back_to_main_menu_button", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
