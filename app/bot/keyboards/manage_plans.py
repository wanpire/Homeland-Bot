from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.services.catalog import format_data_cap, format_price_usd

_CATEGORY_EMOJI = {"trial": "🎁", "scroll": "📜", "stream": "🌊", "trip": "🧳"}


def manage_plans_list_keyboard(plans_by_category: dict[str, list[Plan]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []
    for category, plans in plans_by_category.items():
        emoji = _CATEGORY_EMOJI.get(category, "")
        for plan in plans:
            status = "✅" if plan.is_active else "🚫"
            builder.button(
                text=f"{emoji} {plan.name} — {format_price_usd(plan.price_usd)} {status}",
                callback_data=f"adm:settings:plan:{plan.id}",
            )
            sizes.append(1)
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    sizes.append(1)
    builder.adjust(*sizes)
    return builder.as_markup()


def manage_plans_detail_keyboard(plan: Plan) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit Price", callback_data=f"adm:settings:plan:{plan.id}:price")
    toggle_label = "🚫 Deactivate" if plan.is_active else "✅ Activate"
    builder.button(text=toggle_label, callback_data=f"adm:settings:plan:{plan.id}:toggle")
    builder.button(text="⬅️ Back to Plans", callback_data="adm:settings:plans")
    builder.adjust(1)
    return builder.as_markup()


def manage_plans_price_edit_cancel_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data=f"adm:settings:plan:{plan_id}")
    builder.adjust(1)
    return builder.as_markup()


def plan_detail_text(plan: Plan) -> str:
    status = "✅ Active" if plan.is_active else "🚫 Inactive"
    return (
        f"💰 <b>{plan.name} ({plan.category})</b>\n\n"
        f"Duration: {plan.duration_days} days\n"
        f"Data cap: {format_data_cap(plan.data_cap_mb, 'en')}\n"
        f"Group: {plan.group_name}\n"
        f"Price: {format_price_usd(plan.price_usd)}\n"
        f"Status: {status}"
    )
