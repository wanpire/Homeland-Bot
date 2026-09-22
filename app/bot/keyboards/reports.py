"""Keyboards for the Reports section.

The period selector appears only on period-based screens; the health
screens describe right now and the backups screen is a file list, so
offering "last 7 days" there would be meaningless."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.reporting import PERIODS


def reports_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Overview", callback_data="adm:reports:overview")
    builder.button(text="🆕 Signups", callback_data="adm:reports:signups")
    builder.button(text="💰 Sales", callback_data="adm:reports:sales")
    builder.button(text="📊 Accounting", callback_data="adm:reports:accounting")
    builder.button(text="🩺 Service Health", callback_data="adm:reports:service")
    builder.button(text="🖥 Server Health", callback_data="adm:reports:server")
    builder.button(text="💾 Backups", callback_data="adm:reports:backups")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def reports_keyboard(active_period: str, *, root: str = "adm:reports:overview") -> InlineKeyboardMarkup:
    """`root` keeps each period button on the screen it belongs to, so
    switching period on Sales does not bounce the admin to Overview."""
    builder = InlineKeyboardBuilder()
    for key, period in PERIODS.items():
        label = f"• {period.label}" if key == active_period else period.label
        builder.button(text=label, callback_data=f"{root}:{key}")
    builder.button(text="⬅️ Back to Reports", callback_data="adm:reports")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def health_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Reports", callback_data="adm:reports")
    builder.adjust(1)
    return builder.as_markup()


def backups_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Reports", callback_data="adm:reports")
    builder.adjust(1)
    return builder.as_markup()
