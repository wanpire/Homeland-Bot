from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.services.catalog import format_data_cap, format_price_usd


def renew_service_keyboard(rows: list[tuple[VPNUser, Plan | None]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        builder.button(text=name, callback_data=f"renew:service:{vpn_user.id}")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def renew_empty_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Buy Subscription", callback_data="menu:buy", style="success")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def renew_category_keyboard(vpn_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Scroll", callback_data=f"renew:category:{vpn_user_id}:scroll")
    builder.button(text="🌊 Stream", callback_data=f"renew:category:{vpn_user_id}:stream")
    builder.button(text="⬅️ Back to Services", callback_data="menu:renew")
    builder.adjust(2, 1)
    return builder.as_markup()


def renew_plan_keyboard(plans: list[Plan], vpn_user_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan.name} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb)})",
            callback_data=f"renew:plan:{vpn_user_id}:{plan.id}",
        )
    builder.button(text="⬅️ Back", callback_data=f"renew:service:{vpn_user_id}")
    builder.adjust(1)
    return builder.as_markup()
