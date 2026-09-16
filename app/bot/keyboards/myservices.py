from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser

_STATUS_BADGE = {
    "active": "✅ Active",
    "expired": "⛔ Expired",
    "pending": "⏳ Pending",
    "unknown": "⚠️ Unknown",
}


def myservices_empty_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Buy Subscription", callback_data="menu:buy", style="success")
    builder.button(text="🎁 Free Trial", callback_data="menu:trial", style="success")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_list_keyboard(rows: list[tuple[VPNUser, Plan | None, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan, status in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        builder.button(
            text=f"{name} — {_STATUS_BADGE[status]}",
            callback_data=f"myservices:view:{vpn_user.id}",
        )
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def myservices_detail_keyboard(vpn_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Resend Setup", callback_data=f"myservices:resend:{vpn_user_id}")
    builder.button(text="⬅️ Back to List", callback_data="menu:myservices")
    builder.adjust(1)
    return builder.as_markup()
