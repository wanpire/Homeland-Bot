from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_root_menu(*, is_sales_admin: bool, is_full_admin: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Users", callback_data="adm:users")
    builder.button(text="📚 Tutorials & Profiles", callback_data="adm:tutorials")
    sizes = [1, 1]
    if is_sales_admin:
        builder.button(text="🏷 Discount Codes", callback_data="adm:discounts")
        sizes.append(1)
    if is_full_admin:
        # Broadcast's router is gated IsFullAdmin, so it is HIDDEN rather
        # than merely filter-gated here - per spec §2, a visible button
        # whose filter silently rejects the tap gives a lower-tier admin
        # zero feedback (Telegram just spins forever).
        builder.button(text="📢 Broadcast", callback_data="adm:broadcast")
        sizes.append(1)
        builder.button(text="👥 Manage Admins", callback_data="adm:admins")
        sizes.append(1)
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
    builder.button(text="📢 Mandatory Channel", callback_data="adm:settings:channel")
    builder.button(text="⏰ Renewal Reminders", callback_data="adm:settings:reminders")
    builder.button(text="🎁 Free Trial", callback_data="adm:settings:trial")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
