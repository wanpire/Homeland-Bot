"""Keyboards for Financial → Sales Status.

The switch button names the state it SETS, never "toggle": a stale
keyboard tapped after another admin already disabled sales must not
quietly turn them back on."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def sales_status_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if enabled:
        builder.button(text="🔴 Disable Sales", callback_data="adm:fin:sales:set:off")
    else:
        builder.button(text="🟢 Enable Sales", callback_data="adm:fin:sales:set:on")
    builder.button(text="✏️ Edit Message (FA)", callback_data="adm:fin:sales:msg:fa")
    builder.button(text="✏️ Edit Message (EN)", callback_data="adm:fin:sales:msg:en")
    builder.button(text="↩️ Reset Messages to Default", callback_data="adm:fin:sales:reset")
    builder.button(text="⬅️ Back to Financial", callback_data="adm:fin")
    builder.adjust(1)
    return builder.as_markup()


def sales_message_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:fin:sales")
    builder.adjust(1)
    return builder.as_markup()
