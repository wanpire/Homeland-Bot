"""Period picker for the Reports screen.

The same four periods Financial offers, from the same definitions, so a
figure here and the same figure there cannot disagree."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.reporting import PERIODS


def reports_keyboard(active_period: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, period in PERIODS.items():
        label = f"• {period.label}" if key == active_period else period.label
        builder.button(text=label, callback_data=f"adm:reports:{key}")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
