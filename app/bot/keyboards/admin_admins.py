from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.admin_user import AdminUser
from app.services.admin_users import LEVEL_LABELS


def admin_admins_list_keyboard(rows: list[tuple[AdminUser, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for admin, display in rows:
        builder.button(
            text=f"🗑 {display} — {LEVEL_LABELS[admin.level]}",
            callback_data=f"adm:admins:remove:{admin.telegram_id}",
        )
    builder.button(text="➕ Add Admin", callback_data="adm:admins:add", style="success")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    sizes = [1] * len(rows) + [1, 1]
    builder.adjust(*sizes)
    return builder.as_markup()


def add_admin_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:admins")
    builder.adjust(1)
    return builder.as_markup()


def add_admin_level_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Support", callback_data="adm:admins:add:level:support")
    builder.button(text="Sales", callback_data="adm:admins:add:level:sales")
    builder.button(text="Full", callback_data="adm:admins:add:level:full")
    builder.button(text="❌ Cancel", callback_data="adm:admins")
    builder.adjust(3, 1)
    return builder.as_markup()


def remove_admin_confirm_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yes, Remove", callback_data=f"adm:admins:remove:confirm:{telegram_id}", style="danger")
    builder.button(text="❌ Cancel", callback_data="adm:admins")
    builder.adjust(1)
    return builder.as_markup()


def back_to_admins_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Admins", callback_data="adm:admins")
    builder.adjust(1)
    return builder.as_markup()
