from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.discount_code import DiscountCode
from app.db.models.plan import Plan

WIZARD_CANCEL_CB = "adm:discounts"


def discount_list_keyboard(discounts: list[DiscountCode]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in discounts:
        marker = "✅" if d.is_active else "⛔️"
        builder.button(text=f"{marker} {d.code} (-{d.percent}%)", callback_data=f"adm:discounts:view:{d.id}")
    builder.button(text="➕ New Discount Code", callback_data="adm:discounts:new")
    builder.button(text="⬅️ Back to Financial", callback_data="adm:fin")
    builder.adjust(1)
    return builder.as_markup()


def discount_detail_keyboard(discount: DiscountCode) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit", callback_data=f"adm:discounts:edit:{discount.id}")
    toggle_label = "⛔️ Deactivate" if discount.is_active else "✅ Activate"
    builder.button(text=toggle_label, callback_data=f"adm:discounts:toggle:{discount.id}")
    builder.button(text="🗑 Delete", callback_data=f"adm:discounts:delete:{discount.id}")
    builder.button(text="⬅️ Back to List", callback_data="adm:discounts")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def discount_delete_confirm_keyboard(discount_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Yes, delete", callback_data=f"adm:discounts:delete:{discount_id}:confirm")
    builder.button(text="❌ Cancel", callback_data=f"adm:discounts:view:{discount_id}")
    builder.adjust(1)
    return builder.as_markup()


def wizard_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()


def wizard_usage_limit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Unlimited", callback_data="adm:discounts:wizard:unlimited")
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(1)
    return builder.as_markup()


def wizard_plans_keyboard(plans: list[Plan], selected_ids: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    all_selected = len(selected_ids) == len(plans)
    for plan in plans:
        mark = "☑️" if plan.id in selected_ids else "▫️"
        builder.button(text=f"{mark} {plan.name}", callback_data=f"adm:discounts:wizard:plan:{plan.id}")
    builder.button(
        text="◻️ Deselect All" if all_selected else "🔘 Select All",
        callback_data="adm:discounts:wizard:allplans",
    )
    builder.button(text="✅ Done", callback_data="adm:discounts:wizard:plansdone")
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(*([1] * len(plans)), 1, 1, 1)
    return builder.as_markup()


def wizard_visibility_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🌍 Public", callback_data="adm:discounts:wizard:public")
    builder.button(text="🔒 Private", callback_data="adm:discounts:wizard:private")
    builder.button(text="❌ Cancel", callback_data=WIZARD_CANCEL_CB)
    builder.adjust(2, 1)
    return builder.as_markup()
