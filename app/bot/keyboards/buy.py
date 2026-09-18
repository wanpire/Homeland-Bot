from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.i18n.texts import t
from app.services.catalog import category_display_name, format_data_cap, format_price_usd, plan_display_name


_BUY_CATEGORY_ORDER = ("scroll", "stream", "trip")


def buy_category_keyboard(lang: str, active_categories: set[str]) -> InlineKeyboardMarkup:
    """Only renders a category that actually has at least one active plan -
    tapping one that has none is a dead end (an empty tier list with no
    explanation). `active_categories` comes from the handler, which has
    the DB session; this keyboard stays pure and synchronous like every
    other one here.

    If nothing at all is active (currently unreachable - Scroll, Trip and
    Trial are all live - but theoretically possible if an admin
    deactivated everything) it falls back to rendering all three rather
    than a category-less screen. Back to Menu is added unconditionally, so
    this keyboard is never a trap regardless of what's active."""
    shown = [c for c in _BUY_CATEGORY_ORDER if c in active_categories] or list(_BUY_CATEGORY_ORDER)
    builder = InlineKeyboardBuilder()
    for category in shown:
        builder.button(text=category_display_name(category, lang), callback_data=f"buy:category:{category}")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(*category_row_sizes(len(shown)))
    return builder.as_markup()


def category_row_sizes(count: int) -> tuple[int, ...]:
    """Keeps the original 2-then-1-per-row shape when all three categories
    render, and degrades sensibly when fewer do. The trailing 1 is the
    always-present Back button's own row."""
    if count >= 3:
        return (2,) + (1,) * (count - 2) + (1,)
    return (1,) * (count + 1)


def buy_plan_keyboard(plans: list[Plan], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{plan_display_name(plan, lang)} — {format_price_usd(plan.price_usd)} ({format_data_cap(plan.data_cap_mb, lang)})",
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
