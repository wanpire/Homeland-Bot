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
from decimal import Decimal

import httpx

from app.config import get_settings

_BASE_URL = "https://api.nowpayments.io/v1"


class NowPaymentsError(Exception):
    """Raised when the NOWPayments API returns an error."""


class PaymentProviderNotConfiguredError(Exception):
    """Raised instead of a confusing raw API failure when nowpayments_api_key
    is blank - lets the bot run with crypto payment visibly unavailable
    until real keys are provisioned."""


async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
    """Returns (invoice_url, payment_id) - payment_id is NOWPayments'
    own id for this invoice, stored on Payment.provider_payment_id for
    IPN lookup."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

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

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{_BASE_URL}/invoice", json=payload, headers=headers)

    if response.status_code >= 400:
        raise NowPaymentsError(f"NOWPayments invoice creation failed: {response.status_code} {response.text}")

    data = response.json()
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
