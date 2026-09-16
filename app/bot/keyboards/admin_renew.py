from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.services.catalog import format_price_usd


def admin_renew_username_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:users")
    builder.adjust(1)
    return builder.as_markup()


def admin_renew_plan_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan.name} — {format_price_usd(plan.price_usd)}",
            callback_data=f"adm:users:renew:plan:{plan.id}",
        )
    builder.button(text="❌ Cancel", callback_data="adm:users")
    builder.adjust(1)
    return builder.as_markup()


def admin_renew_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Users", callback_data="adm:users")
    builder.adjust(1)
    return builder.as_markup()
