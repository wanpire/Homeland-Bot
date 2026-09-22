from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_root_menu(*, is_sales_admin: bool, is_full_admin: bool) -> InlineKeyboardMarkup:
    """Seven entries, grouped by what an admin is trying to do rather
    than by the order features happened to ship in.

    A button a tier cannot use is HIDDEN, never shown-and-filtered:
    Telegram gives no feedback at all when a router filter silently
    rejects a tap, so the button would just spin forever."""
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    builder.button(text="👤 Users", callback_data="adm:users")
    sizes.append(1)
    if is_sales_admin:
        builder.button(text="💰 Financial", callback_data="adm:fin")
        builder.button(text="📊 Reports", callback_data="adm:reports")
        sizes.append(2)
    builder.button(text="📚 Tutorials & Profiles", callback_data="adm:tutorials")
    sizes.append(1)
    if is_full_admin:
        builder.button(text="📢 Broadcast", callback_data="adm:broadcast")
        builder.button(text="⚙️ System", callback_data="adm:settings")
        sizes.append(2)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    sizes.append(1)

    builder.adjust(*sizes)
    return builder.as_markup()


def admin_financial_menu(*, is_full_admin: bool) -> InlineKeyboardMarkup:
    """Everything about money in one place. Discount Codes, Manage Plans
    and the crypto screens moved here from the root menu and Settings -
    their callbacks are unchanged, so a keyboard already sitting in an
    admin's chat history still works."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Revenue Overview", callback_data="adm:fin:revenue")
    builder.button(text="🧾 Payments", callback_data="adm:fin:payments")
    builder.button(text="🏷 Discount Codes", callback_data="adm:discounts")
    builder.button(text="💰 Manage Plans", callback_data="adm:settings:plans")
    if is_full_admin:
        builder.button(text="💳 Crypto Settlement Address", callback_data="adm:settings:crypto")
        builder.button(text="💱 Crypto Coins", callback_data="adm:settings:coins")
        builder.button(text="🔄 Recover Stuck Payments", callback_data="adm:settings:reconcile")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()


def back_to_admin_root_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()


def back_to_financial_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Financial", callback_data="adm:fin")
    builder.adjust(1)
    return builder.as_markup()


def admin_users_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="♻️ Renew a Service", callback_data="adm:users:renew")
    builder.button(text="🚫 Blocked Users", callback_data="adm:users:blocked:0")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()


def admin_settings_menu() -> InlineKeyboardMarkup:
    """System plumbing only. The money screens that used to live here
    moved to Financial; Manage Admins moved in from the root menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="☎️ Support Contact", callback_data="adm:settings:support")
    builder.button(text="🔄 Sync IBSng Groups", callback_data="adm:settings:syncgroups")
    builder.button(text="📢 Mandatory Channel", callback_data="adm:settings:channel")
    builder.button(text="⏰ Renewal Reminders", callback_data="adm:settings:reminders")
    builder.button(text="🎁 Trial Limit", callback_data="adm:settings:trial")
    builder.button(text="👥 Manage Admins", callback_data="adm:admins")
    builder.button(text="⬅️ Back to Admin Panel", callback_data="adm:root")
    builder.adjust(1)
    return builder.as_markup()
