"""Keyboards for the coin chooser and for the below-minimum screen that
replaces the old dead end. Coin labels are proper nouns (USDT (TRC-20),
TRX) and are deliberately NOT translated; every other string here goes
through t()."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t
from app.services.payments.currencies import PayCurrency


def pay_currency_keyboard(
    currencies: list[PayCurrency], *, pay_prefix: str, back_cb: str, lang: str
) -> InlineKeyboardMarkup:
    """One button per coin that can pay this amount right now. The caller
    filtered the list - this keyboard never renders a coin the buyer
    would then be refused for."""
    builder = InlineKeyboardBuilder()
    for currency in currencies:
        builder.button(text=currency.label, callback_data=f"{pay_prefix}:{currency.code}", style="success")
    builder.button(text=t("back_button", lang), callback_data=back_cb)
    builder.adjust(1)
    return builder.as_markup()


def below_minimum_keyboard(*, back_to_plans_cb: str, lang: str) -> InlineKeyboardMarkup:
    """Never a dead end: a buyer told their plan is below every network
    minimum needs a one-tap route to a pricier plan."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("back_to_plans_button", lang), callback_data=back_to_plans_cb)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
