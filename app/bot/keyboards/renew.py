from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.buy import category_row_sizes
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.i18n.texts import t
from app.services.catalog import category_display_name, format_data_cap, format_price_usd, plan_display_name

_RENEW_CATEGORY_ORDER = ("scroll", "stream", "trip")


def renew_service_keyboard(rows: list[tuple[VPNUser, Plan | None]], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan in rows:
        name = plan_display_name(plan, lang) if plan is not None else vpn_user.ibsng_group
        builder.button(text=name, callback_data=f"renew:service:{vpn_user.id}")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def renew_empty_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("menu_buy", lang), callback_data="menu:buy", style="success")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def renew_category_keyboard(vpn_user_id: int, lang: str, active_categories: set[str]) -> InlineKeyboardMarkup:
    """Same dead-end-category rule as buy_category_keyboard - see its
    docstring. Back to List always renders, whatever is active."""
    shown = [c for c in _RENEW_CATEGORY_ORDER if c in active_categories] or list(_RENEW_CATEGORY_ORDER)
    builder = InlineKeyboardBuilder()
    for category in shown:
        builder.button(
            text=category_display_name(category, lang),
            callback_data=f"renew:category:{vpn_user_id}:{category}",
        )
    builder.button(text=t("back_to_list_button", lang), callback_data="menu:renew")
    builder.adjust(*category_row_sizes(len(shown)))
    return builder.as_markup()


def renew_plan_keyboard(plans: list[Plan], vpn_user_id: int, category: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan_display_name(plan, lang)} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb, lang)})",
            callback_data=f"renew:plan:{vpn_user_id}:{plan.id}",
        )
    builder.button(text=t("back_button", lang), callback_data=f"renew:service:{vpn_user_id}")
    builder.adjust(1)
    return builder.as_markup()


def renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("pay_with_crypto_button", lang), callback_data=f"renew:confirm:{vpn_user_id}:{plan_id}", style="success")
    builder.button(text=t("back_button", lang), callback_data=f"renew:category:{vpn_user_id}:{category}")
    builder.adjust(1)
    return builder.as_markup()
