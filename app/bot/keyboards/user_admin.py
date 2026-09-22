"""Keyboards for the admin's customer detail view."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.user_admin import UserOverview


def user_search_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:users")
    builder.adjust(1)
    return builder.as_markup()


def user_detail_keyboard(overview: UserOverview, *, can_see_payments: bool) -> InlineKeyboardMarkup:
    """Block and Renew live here rather than on separate menus: an admin
    helping a customer already has them on screen."""
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    toggle = "✅ Unblock" if overview.is_blocked else "🚫 Block"
    builder.button(text=toggle, callback_data=f"adm:users:toggleblock:{overview.telegram_id}")
    sizes.append(1)

    for service in overview.services:
        builder.button(
            text=f"♻️ Renew {service.ibsng_username}",
            callback_data=f"adm:users:renewsvc:{service.vpn_user_id}",
        )
        sizes.append(1)

    if can_see_payments:
        # Financial is sales-gated, so a support admin is not offered a
        # link they would only be refused.
        builder.button(
            text="🧾 Payments for this user",
            callback_data=f"adm:fin:payments:all:all:0",
        )
        sizes.append(1)

    builder.button(text="🔍 Find another", callback_data="adm:users:find")
    builder.button(text="⬅️ Back to Users", callback_data="adm:users")
    sizes += [1, 1]

    builder.adjust(*sizes)
    return builder.as_markup()
