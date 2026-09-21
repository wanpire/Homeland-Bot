"""The coins Homeland accepts, resolved from Settings rather than
hardcoded, so adding one (TON, USDT-TON, ...) is a .env change plus an
optional label here. Deliberately holds NO minimum amounts - those are
live per-coin values from NOWPayments, see minimums.py."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class PayCurrency:
    code: str  # NOWPayments currency code, lowercase
    label: str  # customer-facing; a proper noun, never translated


# Display names only. A code missing here still works - it falls back to
# code.upper() - so a new coin needs no code change at all.
_LABELS: dict[str, str] = {
    "usdttrc20": "USDT (TRC-20)",
    "usdtbsc": "USDT (BEP-20)",
    "trx": "TRX (Tron)",
    "ltc": "LTC (Litecoin)",
    "ton": "TON",
    "usdtton": "USDT (TON)",
}


def accepted_currencies() -> list[PayCurrency]:
    return [
        PayCurrency(code=code, label=_LABELS.get(code, code.upper()))
        for code in get_settings().nowpayments_pay_currency_list
    ]


def find_currency(code: str) -> PayCurrency | None:
    """None for any code not currently accepted - callers use this to
    reject a stale keyboard's coin rather than trusting callback data."""
    wanted = code.strip().lower()
    return next((currency for currency in accepted_currencies() if currency.code == wanted), None)
