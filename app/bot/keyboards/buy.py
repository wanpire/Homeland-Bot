from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.i18n.texts import t
from app.services.catalog import category_display_name, format_data_cap, format_price_usd, plan_display_name


def buy_category_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=category_display_name("scroll", lang), callback_data="buy:category:scroll")
    builder.button(text=category_display_name("stream", lang), callback_data="buy:category:stream")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def buy_plan_keyboard(plans: list[Plan], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan_display_name(plan, lang)} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb)})",
            callback_data=f"buy:plan:{plan.id}",
        )
    builder.button(text=t("back_button", lang), callback_data="menu:buy")
    builder.adjust(1)
    return builder.as_markup()


def buy_price_summary_keyboard(plan_id: int, category: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("pay_with_crypto_button", lang), callback_data=f"buy:confirm:{plan_id}", style="success")
    builder.button(text=t("back_button", lang), callback_data=f"buy:category:{category}")
    builder.adjust(1)
    return builder.as_markup()


def payment_link_keyboard(invoice_url: str, lang: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("open_payment_page_button", lang), url=invoice_url)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
