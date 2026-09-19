from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

CANCEL_CB = "adm:broadcast:cancel"
CONFIRM_CB = "adm:broadcast:confirm"


def broadcast_compose_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data=CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Send", callback_data=CONFIRM_CB, style="success")
    builder.button(text="❌ Cancel", callback_data=CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()


def broadcast_submenu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📣 Announcement", callback_data="adm:broadcast:announce")
    builder.button(text="🎯 Ad Campaign", callback_data="adm:broadcast:campaign")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
