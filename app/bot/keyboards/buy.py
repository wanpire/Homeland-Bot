from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.services.catalog import format_data_cap, format_price_usd


def buy_category_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Scroll", callback_data="buy:category:scroll")
    builder.button(text="🌊 Stream", callback_data="buy:category:stream")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def buy_plan_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan.name} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb)})",
            callback_data=f"buy:plan:{plan.id}",
        )
    builder.button(text="⬅️ Back", callback_data="menu:buy")
    builder.adjust(1)
    return builder.as_markup()


def buy_price_summary_keyboard(plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Buy", callback_data=f"buy:confirm:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"buy:category:{category}")
    builder.adjust(1)
    return builder.as_markup()
