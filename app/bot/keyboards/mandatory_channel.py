from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def join_channels_keyboard(missing_usernames: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for username in missing_usernames:
        builder.button(text=f"📢 Join @{username}", url=f"https://t.me/{username}")
    builder.button(text="✅ I've Joined", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
