from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# The coins Homeland's NOWPayments dashboard is configured to accept
# (see app/services/payments/nowpayments.py's _MIN_AMOUNT_CURRENCIES) -
# code -> display label. Kept here rather than imported from nowpayments.py
# so this admin-only UI module never depends on the payments module for
# anything beyond the client calls it already makes directly.
NETWORK_LABELS: dict[str, str] = {
    "usdttrc20": "USDT (TRC20)",
    "usdtbsc": "USDT (BEP20/BSC)",
    "trx": "TRX",
    "ltc": "LTC",
}


def crypto_settlement_status_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit", callback_data="adm:settings:crypto:edit")
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()


def crypto_network_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label in NETWORK_LABELS.items():
        builder.button(text=label, callback_data=f"adm:settings:crypto:network:{code}")
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings:crypto")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def crypto_settlement_edit_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="adm:settings:crypto")
    builder.adjust(1)
    return builder.as_markup()
