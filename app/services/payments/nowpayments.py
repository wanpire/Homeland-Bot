"""Client for NOWPayments' hosted Invoice API. We use the Invoice flow
(not the raw Payment API) so NOWPayments handles coin selection, address
generation, and the QR/payment page entirely - we only need an
invoice_url to hand the buyer and an IPN webhook to hear back. Ported
from the sibling project's app/services/nowpayments.py - see
docs/superpowers/specs/2026-09-16-crypto-payment-design.md.

Reference: https://documenter.getpostman.com/view/7907941/S1a32n38
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.nowpayments.io/v1"



class NowPaymentsError(Exception):
    """Raised when the NOWPayments API returns an error."""


class PaymentProviderNotConfiguredError(Exception):
    """Raised instead of a confusing raw API failure when nowpayments_api_key
    is blank - lets the bot run with crypto payment visibly unavailable
    until real keys are provisioned."""


class PaymentBelowMinimumError(Exception):
    """Raised when NOWPayments rejects an amount as below a coin's
    minimum payable amount. The coin chooser
    (app/services/payments/minimums.py) normally prevents this; when a
    minimum moves inside the cache window it still happens, and the
    caller recovers by invalidating that coin and re-offering the
    chooser rather than dead-ending the buyer."""


async def get_min_amount(*, currency_from: str) -> Decimal:
    """The minimum payable amount for currency_from in USD, via
    NOWPayments' own "fiat_equivalent" field - NOT the "min_amount"
    field, which is denominated in currency_from's own units (e.g.
    "0.21" for LTC), not USD. Confirmed against the real API on
    2026-09-18.

    currency_to is ALWAYS sent, set to our settlement currency. The API
    docs claim that omitting it falls back to the outcome currency
    configured in Payment Settings; live testing on 2026-09-21 proved
    otherwise - omitted, the response carries currency_to="false" and
    prices the coin against ITSELF, reporting TRX at $0.25 rather than
    its true $12.31 against USDT TRC-20. Trusting that would offer coins
    for plans they cannot actually pay, which is the exact dead end this
    lookup exists to prevent."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    headers = {"x-api-key": settings.nowpayments_api_key}
    params = {
        "currency_from": currency_from,
        "currency_to": settings.nowpayments_settlement_currency,
        "fiat_equivalent": "usd",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{_BASE_URL}/min-amount", params=params, headers=headers)
    except httpx.RequestError as exc:
        raise NowPaymentsError(f"NOWPayments min-amount request failed: {exc}") from exc

    if response.status_code >= 400:
        raise NowPaymentsError(f"NOWPayments min-amount lookup failed: {response.status_code} {response.text}")

    try:
        data = response.json()
    except ValueError as exc:
        raise NowPaymentsError(f"NOWPayments min-amount response was not valid JSON: {exc}") from exc

    fiat_equivalent = data.get("fiat_equivalent")
    if fiat_equivalent is None:
        raise NowPaymentsError(f"NOWPayments min-amount response missing fiat_equivalent: {data!r}")
    try:
        return Decimal(str(fiat_equivalent))
    except InvalidOperation as exc:
        raise NowPaymentsError(f"NOWPayments min-amount response had a non-numeric fiat_equivalent: {data!r}") from exc


async def validate_payout_address(*, address: str, currency: str) -> tuple[bool, str | None]:
    """Returns (is_valid, error_message). NOWPayments' own quirk,
    confirmed against the real API on 2026-09-18: a VALID address
    returns the plain-text body "OK" (not JSON); an INVALID one returns
    a JSON error body with a human-readable "message" field."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    headers = {"x-api-key": settings.nowpayments_api_key, "Content-Type": "application/json"}
    payload = {"address": address, "currency": currency}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{_BASE_URL}/payout/validate-address", json=payload, headers=headers)
    except httpx.RequestError as exc:
        raise NowPaymentsError(f"NOWPayments address validation request failed: {exc}") from exc

    if response.status_code == 200 and response.text.strip() == "OK":
        return True, None

    if response.status_code == 400:
        try:
            data = response.json()
        except ValueError:
            return False, response.text or "Address validation failed."
        message = data.get("message") if isinstance(data, dict) else None
        return False, message or "Address validation failed."

    # Any other status (401 bad key, 500, etc.) is a real API failure,
    # not a verdict on the address - must not be reported to the admin
    # as "invalid address".
    raise NowPaymentsError(f"NOWPayments address validation failed: {response.status_code} {response.text}")


async def create_invoice(
    *, order_id: str, amount: Decimal, description: str, pay_currency: str | None = None
) -> tuple[str, str]:
    """Returns (invoice_url, payment_id) - payment_id is NOWPayments'
    own id for this invoice, stored on Payment.provider_payment_id for
    IPN lookup.

    pay_currency locks the hosted payment page to one coin, so a buyer
    can no longer pick a coin whose minimum exceeds the price and
    dead-end there; the caller picked it from a PayabilityReport."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    payload: dict[str, str] = {
        "price_amount": str(amount),
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": description,
    }
    if pay_currency:
        payload["pay_currency"] = pay_currency
    if settings.nowpayments_ipn_callback_url:
        payload["ipn_callback_url"] = settings.nowpayments_ipn_callback_url
    if settings.bot_username:
        payload["success_url"] = f"https://t.me/{settings.bot_username}"
        payload["cancel_url"] = f"https://t.me/{settings.bot_username}"

    headers = {"x-api-key": settings.nowpayments_api_key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{_BASE_URL}/invoice", json=payload, headers=headers)
    except httpx.RequestError as exc:
        raise NowPaymentsError(f"NOWPayments request failed: {exc}") from exc

    if response.status_code >= 400:
        # Defensive only. Verified live on 2026-09-21: NOWPayments does
        # NOT reject a below-minimum invoice at creation - it returned
        # 200 for $3.00 locked to TRX, whose minimum is $12.31, and the
        # failure would only surface to the buyer on the hosted page.
        # The payability pre-check is therefore the ONLY thing standing
        # between a buyer and that dead end; this branch just means that
        # if NOWPayments ever does reject one (the /v1/payment endpoint
        # returns AMOUNT_MINIMAL_ERROR today), we recover by dropping the
        # cached value and re-offering the chooser instead of showing a
        # generic error.
        if response.status_code == 400 and "min" in response.text.lower():
            raise PaymentBelowMinimumError(
                f"NOWPayments rejected {amount} USD in {pay_currency or 'any coin'} as below minimum: {response.text}"
            )
        raise NowPaymentsError(f"NOWPayments invoice creation failed: {response.status_code} {response.text}")

    try:
        data = response.json()
    except ValueError as exc:
        raise NowPaymentsError(f"NOWPayments response was not valid JSON: {exc}") from exc

    invoice_url = data.get("invoice_url")
    payment_id = data.get("id")
    if not invoice_url or not payment_id:
        raise NowPaymentsError(f"NOWPayments response missing invoice_url/id: {data!r}")
    return invoice_url, str(payment_id)


def verify_ipn_signature(raw_body: bytes, signature: str, ipn_secret: str) -> bool:
    """NOWPayments signs a sorted-keys JSON encoding of the IPN payload
    with HMAC-SHA512 using the IPN secret (separate from the API key) -
    exact technique ported from the sibling project's nowpayments.py."""
    if not signature or not ipn_secret:
        return False
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return False
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(ipn_secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
