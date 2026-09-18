"""Client for NOWPayments' hosted Invoice API. We use the Invoice flow
(not the raw Payment API) so NOWPayments handles coin selection, address
generation, and the QR/payment page entirely - we only need an
invoice_url to hand the buyer and an IPN webhook to hear back. Ported
from the sibling project's app/services/nowpayments.py - see
docs/superpowers/specs/2026-09-16-crypto-payment-design.md.

Reference: https://documenter.getpostman.com/view/7907941/S1a32n38
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from decimal import Decimal

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.nowpayments.io/v1"

# The low-fee coins Homeland's NOWPayments dashboard is configured to
# accept (a manual, one-time dashboard setting - not something this code
# controls). Confirmed live against the real API on 2026-09-18: these are
# the exact NOWPayments currency codes - note "usdtbsc" for BEP20, NOT
# "usdtbep20" (that code doesn't exist on this account and 404s).
_MIN_AMOUNT_CURRENCIES: tuple[str, ...] = ("usdttrc20", "usdtbsc", "trx", "ltc")


class NowPaymentsError(Exception):
    """Raised when the NOWPayments API returns an error."""


class PaymentProviderNotConfiguredError(Exception):
    """Raised instead of a confusing raw API failure when nowpayments_api_key
    is blank - lets the bot run with crypto payment visibly unavailable
    until real keys are provisioned."""


class PaymentBelowMinimumError(Exception):
    """Raised by create_invoice when the amount is below every accepted
    coin's minimum payable amount - see check_minimum_amount below."""


async def get_min_amount(*, currency_from: str, currency_to: str = "usd") -> Decimal:
    """The minimum payable amount for currency_from, expressed in
    currency_to via NOWPayments' own "fiat_equivalent" field - NOT the
    "min_amount" field, which is denominated in currency_from's own
    units (e.g. "0.21" for LTC), not USD. Confirmed against the real
    API on 2026-09-18."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    headers = {"x-api-key": settings.nowpayments_api_key}
    params = {"currency_from": currency_from, "currency_to": currency_to, "fiat_equivalent": currency_to}

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
    return Decimal(str(fiat_equivalent))


async def check_minimum_amount(amount_usd: Decimal) -> None:
    """Raises PaymentBelowMinimumError only when amount_usd is
    confirmed below the minimum for EVERY accepted coin - if even one
    coin's minimum is unknown (a transient NOWPayments error) or clears
    the bar, this passes silently. Fail-open on lookup errors rather
    than fail-closed: an outage on this one endpoint must never block
    a purchase that create_invoice itself could still complete."""

    async def _min_or_none(currency: str) -> Decimal | None:
        try:
            return await get_min_amount(currency_from=currency)
        except NowPaymentsError:
            logger.warning("NOWPayments min-amount lookup failed for %s", currency, exc_info=True)
            return None

    results = await asyncio.gather(*(_min_or_none(currency) for currency in _MIN_AMOUNT_CURRENCIES))
    known_minimums = [minimum for minimum in results if minimum is not None]
    if known_minimums and all(amount_usd < minimum for minimum in known_minimums):
        raise PaymentBelowMinimumError(
            f"${amount_usd} is below every accepted coin's minimum (lowest known: ${min(known_minimums)})"
        )


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


async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
    """Returns (invoice_url, payment_id) - payment_id is NOWPayments'
    own id for this invoice, stored on Payment.provider_payment_id for
    IPN lookup."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    await check_minimum_amount(amount)

    payload: dict[str, str] = {
        "price_amount": str(amount),
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": description,
    }
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
