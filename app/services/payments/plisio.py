"""Client for Plisio's invoice API.

Plisio is GET-only: every call is
`GET https://api.plisio.net/api/v1/<action>?api_key=<SECRET_KEY>` and
every response is JSON shaped {"status": "success"|"error", "data": ...},
so a failure can arrive with HTTP 200 and status="error" - check the
body, not just the status code.

One secret key does two jobs: it authenticates API calls AND signs the
callbacks Plisio POSTs back (HMAC-SHA1 over the payload). There is no
second IPN secret, unlike the NOWPayments integration this replaced.

Reference: https://plisio.net/documentation
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.plisio.net/api/v1"
_TIMEOUT = 20.0


class PlisioError(Exception):
    """Raised when Plisio's API errors, is unreachable, or answers with a
    body this client cannot use."""


class PaymentProviderNotConfiguredError(Exception):
    """Raised instead of a confusing API failure when plisio_secret_key is
    blank - lets the bot run with crypto visibly unavailable until a real
    key is provisioned."""


def _secret_key() -> str:
    key = get_settings().plisio_secret_key
    if not key:
        raise PaymentProviderNotConfiguredError("PLISIO_SECRET_KEY is not set")
    return key


async def _get(action: str, params: dict[str, str]) -> Any:
    """One GET, one JSON envelope unwrapped. Returns the `data` member."""
    query = {**params, "api_key": _secret_key()}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{_BASE_URL}/{action}", params=query)
    except httpx.RequestError as exc:
        raise PlisioError(f"Plisio {action} request failed: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise PlisioError(
            f"Plisio {action} returned non-JSON (http {response.status_code}): {response.text[:200]}"
        ) from exc

    if not isinstance(body, dict) or body.get("status") != "success":
        data = body.get("data") if isinstance(body, dict) else None
        message = data.get("message") if isinstance(data, dict) else None
        code = data.get("code") if isinstance(data, dict) else None
        raise PlisioError(
            f"Plisio {action} failed (http {response.status_code}, code {code}): "
            f"{message or response.text[:200]}"
        )
    return body.get("data")


async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
    """Create a USD-priced invoice. Returns (invoice_url, txn_id).

    No coin is locked: allowed_psys_cids names every coin this account
    accepts and the buyer picks one on Plisio's own page, switching
    freely if a coin doesn't suit them. That is why this integration
    needs no per-coin minimum pre-check - see
    docs/superpowers/specs/2026-09-22-plisio-migration-design.md §4."""
    settings = get_settings()
    params = {
        "source_currency": "USD",
        "source_amount": str(amount),
        "order_number": order_id,
        "order_name": description,
        "allowed_psys_cids": ",".join(settings.plisio_pay_currency_list),
    }
    if settings.plisio_callback_url:
        params["callback_url"] = settings.plisio_callback_url
    if settings.bot_username:
        # "To the site" buttons on Plisio's invoice page - cosmetic only;
        # real confirmation always arrives via the callback.
        params["success_invoice_url"] = f"https://t.me/{settings.bot_username}"
        params["fail_invoice_url"] = f"https://t.me/{settings.bot_username}"

    data = await _get("invoices/new", params)
    invoice_url = data.get("invoice_url") if isinstance(data, dict) else None
    txn_id = data.get("txn_id") if isinstance(data, dict) else None
    if not invoice_url or not txn_id:
        raise PlisioError(f"Plisio invoice response missing invoice_url/txn_id: {data!r}")
    return str(invoice_url), str(txn_id)


async def list_currencies() -> list[dict[str, Any]]:
    """Every coin Plisio knows, with live rate, min_sum_in and whether
    this account has it enabled. Read-only, for the admin screen."""
    data = await _get("currencies/USD", {})
    if not isinstance(data, list):
        raise PlisioError(f"Plisio currencies response was not a list: {data!r}")
    return [row for row in data if isinstance(row, dict)]


def _candidate_encodings(payload: dict[str, Any]) -> list[str]:
    """The two serializations Plisio's own examples document.

    The Node example - the one that applies to json=true callbacks, which
    is the only variant a non-PHP integration can verify - hashes the
    payload in its RECEIVED key order. The PHP example ksorts first. They
    disagree, and rejecting a genuine callback means a paying customer
    never gets their service, so both are accepted: each is still an HMAC
    under the secret, so this concedes nothing to an attacker."""
    compact = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    sorted_compact = json.dumps(dict(sorted(payload.items())), separators=(",", ":"), ensure_ascii=False)
    return [compact] if compact == sorted_compact else [compact, sorted_compact]


def verify_callback(raw_body: bytes) -> dict[str, Any] | None:
    """Verify a Plisio callback and return its payload, or None.

    Plisio signs with HMAC-SHA1 (NOT SHA512) keyed with the same
    SECRET_KEY used for API calls, over the payload with verify_hash
    removed. The hash travels INSIDE the body, not in a header. This only
    works when the registered callback URL carries ?json=true; otherwise
    Plisio sends a PHP-serialized form post instead."""
    try:
        secret = _secret_key()
    except PaymentProviderNotConfiguredError:
        logger.error("Plisio callback received but PLISIO_SECRET_KEY is not set - cannot verify")
        return None

    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        logger.warning("Plisio callback body was not valid JSON")
        return None
    if not isinstance(payload, dict):
        return None

    received = payload.get("verify_hash")
    if not isinstance(received, str) or not received:
        logger.warning("Plisio callback had no verify_hash")
        return None

    unsigned = {key: value for key, value in payload.items() if key != "verify_hash"}
    for index, encoded in enumerate(_candidate_encodings(unsigned)):
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha1).hexdigest()
        if hmac.compare_digest(expected, received):
            logger.debug("Plisio callback verified using encoding variant %d", index)
            return payload

    logger.warning("Plisio callback failed verify_hash check")
    return None
