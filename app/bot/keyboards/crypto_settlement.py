from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# The coins this Plisio account has wallets for - Plisio currency ID ->
# display label, matching PLISIO_PAY_CURRENCIES. Kept here rather than
# imported from the payments package so this admin-only UI module stays
# independent of it.
NETWORK_LABELS: dict[str, str] = {
    "USDT_TRX": "USDT (TRC-20)",
    "USDT_TON": "USDT (TON)",
    "TON": "TON",
    "TRX": "TRX",
    "LTC": "LTC",
}


def crypto_settlement_status_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit", callback_data="adm:settings:crypto:edit")
    builder.button(text="⬅️ Back to Financial", callback_data="adm:fin")
    builder.adjust(1)
    return builder.as_markup()


def crypto_network_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label in NETWORK_LABELS.items():
        builder.button(text=label, callback_data=f"adm:settings:crypto:network:{code}")
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings:crypto")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def crypto_settlement_edit_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:settings:crypto")
    builder.adjust(1)
    return builder.as_markup()
