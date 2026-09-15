from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_root_menu(*, is_sales_admin: bool, is_full_admin: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Broadcast", callback_data="adm:broadcast")
    builder.button(text="👤 Users", callback_data="adm:users")
    builder.button(text="📚 Tutorials & Profiles", callback_data="adm:tutorials")
    sizes = [1, 1, 1]
    if is_sales_admin:
        builder.button(text="🏷 Discount Codes", callback_data="adm:discounts")
        sizes.append(1)
    if is_full_admin:
        builder.button(text="⚙️ Settings", callback_data="adm:settings")
        sizes.append(1)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    sizes.append(1)
    builder.adjust(*sizes)
    return builder.as_markup()


def admin_users_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="♻️ Renew a Service", callback_data="adm:users:renew")
    builder.button(text="🚫 Blocked Users", callback_data="adm:users:blocked:0")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()


def admin_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
