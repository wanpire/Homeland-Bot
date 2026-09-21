# Plisio Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the NOWPayments crypto integration with Plisio, deleting the per-coin minimum machinery that only existed to work around a NOWPayments limitation Plisio does not have.

**Architecture:** `CryptoProvider` keeps its place behind `PaymentProvider`; a new `app/services/payments/plisio.py` replaces `nowpayments.py`. Invoices are created with `allowed_psys_cids` listing all five configured coins, so the buyer chooses on Plisio's page and the in-bot chooser disappears. Callbacks are verified by HMAC-SHA1 over the JSON body minus `verify_hash`, which requires `?json=true` on the callback URL.

**Tech Stack:** Python 3.12, aiogram 3.x, httpx, SQLAlchemy 2.0 async, aiohttp webhook server, pytest in the isolated Docker stack.

**Spec:** `docs/superpowers/specs/2026-09-22-plisio-migration-design.md`

## Global Constraints

- Plisio's API is **GET only**, `https://api.plisio.net/api/v1/<action>?api_key=<SECRET_KEY>`, JSON `{"status", "data"}`.
- **One secret** signs callbacks and authenticates calls. There is no second IPN secret.
- Currency IDs are exactly `LTC`, `TON`, `USDT_TON`, `USDT_TRX`, `TRX`, from `Settings.plisio_pay_currency_list` — never a literal list in a handler.
- Callback verification is **HMAC-SHA1**, not SHA512, over compact JSON with `verify_hash` removed; accept both received-key order and sorted order (spec §3). Compare with `hmac.compare_digest`.
- Build **no** per-coin minimum check, cache, or payability report. That whole feature is being deleted, not ported.
- Async only, type hints on every signature, thin handlers, no hardcoded secrets.
- Customer strings go through `t(key, lang)` in `fa` and `en`; admin screens stay English and never use `t()`.
- Do not change `Payment`/`PaymentStatusEvent` schemas, the webhook's locking/idempotency, `create_vpn_user`, the aiohttp port, or the `/webhooks/crypto` route path.
- Never print, log, or commit the Plisio secret key.
- Run the suite with `make test`. If the image build hangs on this machine, use the running stack: `docker compose -f docker-compose.test.yml -p homeland_bot_test up -d --no-build`, sync with `tar --exclude=.git --exclude=.claude -cf - app tests alembic alembic.ini pytest.ini requirements*.txt | docker exec -i homeland_bot_test-test-runner-1 tar -xf - -C /app`, reset state with `docker exec homeland_bot_test-db_test-1 psql -U homeland_test -d homeland_test -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`, then `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/ -q`.

---

## File Structure

- **Delete** `app/services/payments/nowpayments.py`, `minimums.py`, `currencies.py`, `app/bot/handlers/_payability.py`, `app/bot/keyboards/payability.py`, `tests/functional/test_nowpayments_client.py`, `test_payability.py`, `test_minimums.py`, `tests/unit/test_currencies.py`.
- **Create** `app/services/payments/plisio.py` — client: `create_invoice`, `list_currencies`, `verify_callback`, `PlisioError`, `PaymentProviderNotConfiguredError`.
- **Create** `tests/functional/test_plisio_client.py`.
- **Modify** `app/config.py` — drop five NOWPayments settings, add three Plisio ones.
- **Modify** `app/services/payments/base.py` — drop `PayabilityReport` and `payable_currencies`; `create_invoice` loses `pay_currency`.
- **Modify** `app/services/payments/crypto_provider.py` — Plisio-backed.
- **Modify** `app/services/payments/service.py` — drop `check_payability` and the `pay_currency` argument.
- **Modify** `app/bot/handlers/buy.py`, `renew.py` — confirm creates the invoice directly; delete the `:pay:` handlers.
- **Modify** `app/i18n/texts.py` — remove four dead keys.
- **Modify** `app/webhook.py` — Plisio status map and payload.
- **Modify** `app/bot/handlers/admin_settings.py`, `app/bot/keyboards/admin.py`, `admin_settings.py` (keyboards), `app/bot/keyboards/crypto_settlement.py` — Crypto Coins screen, no address validation, Plisio network labels.
- **Modify** tests: `test_webhook.py`, `test_buy_flow.py`, `test_renew_flow.py`, `test_payments_service.py`, `test_admin_settings.py`, `test_admin_crypto_settlement.py`, `tests/conftest.py`, `tests/unit/test_config.py`.
- **Modify** docs: `CLAUDE.md`, `.env.example`, `.claude/skills/payment-provider-abstraction/SKILL.md`, header notes on the two superseded specs.

---

## Task 1: Config swap and the Plisio client

**Files:**
- Modify: `app/config.py`
- Create: `app/services/payments/plisio.py`
- Test: `tests/functional/test_plisio_client.py`

**Interfaces:**
- Produces: `Settings.plisio_secret_key`, `Settings.plisio_callback_url`, `Settings.plisio_pay_currencies`, `Settings.plisio_pay_currency_list`; `PlisioError`, `PaymentProviderNotConfiguredError`; `async create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]` returning `(invoice_url, txn_id)`; `async list_currencies() -> list[dict[str, Any]]`; `def verify_callback(raw_body: bytes) -> dict[str, Any] | None`.

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_plisio_client.py`:

```python
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

SECRET = "test-plisio-secret-key"


class _FakeResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text or json.dumps(self._json_data)

    def json(self) -> Any:
        return self._json_data


def _signed(payload: dict[str, Any], *, secret: str = SECRET, sort: bool = False) -> bytes:
    body = dict(sorted(payload.items())) if sort else dict(payload)
    encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    digest = hmac.new(secret.encode(), encoded.encode(), hashlib.sha1).hexdigest()
    return json.dumps({**body, "verify_hash": digest}, separators=(",", ":"), ensure_ascii=False).encode()


@pytest.mark.asyncio
async def test_create_invoice_sends_the_documented_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import plisio

    monkeypatch.setattr(get_settings(), "plisio_callback_url", "https://bot.example/webhooks/crypto?json=true")
    captured: dict[str, Any] = {}

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]) -> _FakeResponse:
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(200, {
            "status": "success",
            "data": {"txn_id": "5ee0e502283675293c450d0e", "invoice_url": "https://plisio.net/invoice/5ee0"},
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    invoice_url, txn_id = await plisio.create_invoice(
        order_id="42", amount=Decimal("12.50"), description="Homeland: 1 Month"
    )

    assert invoice_url == "https://plisio.net/invoice/5ee0"
    assert txn_id == "5ee0e502283675293c450d0e"
    assert captured["url"] == "https://api.plisio.net/api/v1/invoices/new"
    assert captured["params"]["source_currency"] == "USD"
    assert captured["params"]["source_amount"] == "12.50"
    assert captured["params"]["order_number"] == "42"
    assert captured["params"]["order_name"] == "Homeland: 1 Month"
    assert captured["params"]["allowed_psys_cids"] == "LTC,TON,USDT_TON,USDT_TRX,TRX"
    assert captured["params"]["callback_url"] == "https://bot.example/webhooks/crypto?json=true"
    assert captured["params"]["api_key"] == SECRET


@pytest.mark.asyncio
async def test_create_invoice_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import plisio

    monkeypatch.setattr(get_settings(), "plisio_secret_key", "")

    with pytest.raises(plisio.PaymentProviderNotConfiguredError):
        await plisio.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_on_error_status_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plisio reports failures in the body, not only via HTTP codes."""
    from app.services.payments import plisio

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(400, {
            "status": "error",
            "data": {"name": "Bad Request", "message": "Missing required attribute", "code": 103},
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(plisio.PlisioError) as excinfo:
        await plisio.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")
    assert "Missing required attribute" in str(excinfo.value)


@pytest.mark.asyncio
async def test_create_invoice_raises_when_fields_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import plisio

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"status": "success", "data": {"txn_id": "abc"}})  # no invoice_url

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(plisio.PlisioError):
        await plisio.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import plisio

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(plisio.PlisioError):
        await plisio.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


def test_verify_callback_accepts_received_key_order() -> None:
    from app.services.payments import plisio

    payload = {"txn_id": "abc", "order_number": "42", "status": "completed", "amount": "12.5"}
    result = plisio.verify_callback(_signed(payload))
    assert result is not None and result["status"] == "completed"


def test_verify_callback_accepts_sorted_key_order() -> None:
    """The docs' PHP example ksorts; the Node example does not. Genuine
    callbacks must not be rejected over that discrepancy."""
    from app.services.payments import plisio

    payload = {"txn_id": "abc", "order_number": "42", "status": "completed", "amount": "12.5"}
    assert plisio.verify_callback(_signed(payload, sort=True)) is not None


def test_verify_callback_rejects_a_wrong_secret() -> None:
    from app.services.payments import plisio

    payload = {"txn_id": "abc", "order_number": "42", "status": "completed"}
    assert plisio.verify_callback(_signed(payload, secret="not-the-secret")) is None


def test_verify_callback_rejects_a_tampered_field() -> None:
    from app.services.payments import plisio

    signed = json.loads(_signed({"txn_id": "abc", "order_number": "42", "status": "expired"}))
    signed["status"] = "completed"
    assert plisio.verify_callback(json.dumps(signed).encode()) is None


def test_verify_callback_rejects_missing_hash_and_non_json() -> None:
    from app.services.payments import plisio

    assert plisio.verify_callback(json.dumps({"status": "completed"}).encode()) is None
    assert plisio.verify_callback(b"<html>nope</html>") is None


def test_verify_callback_returns_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import plisio

    payload = {"txn_id": "abc", "order_number": "42", "status": "completed"}
    body = _signed(payload)
    monkeypatch.setattr(get_settings(), "plisio_secret_key", "")
    assert plisio.verify_callback(body) is None


@pytest.mark.asyncio
async def test_list_currencies_returns_the_data_list(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import plisio

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]) -> _FakeResponse:
        assert url == "https://api.plisio.net/api/v1/currencies/USD"
        return _FakeResponse(200, {"status": "success", "data": [
            {"cid": "LTC", "name": "Litecoin", "price_usd": "80.00", "min_sum_in": "0.001",
             "hidden": 0, "maintenance": False},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    coins = await plisio.list_currencies()
    assert [c["cid"] for c in coins] == ["LTC"]
```

Update `tests/conftest.py`: replace the `NOWPAYMENTS_*` entries in `_REQUIRED_TEST_ENV` with

```python
    "PLISIO_SECRET_KEY": "test-plisio-secret-key",
    "PLISIO_CALLBACK_URL": "https://bot.test/webhooks/crypto?json=true",
```

and in `tests/unit/test_config.py` change the env-clearing prefix tuple's `"NOWPAYMENTS_"` to `"PLISIO_"`, plus rename `test_settings_nowpayments_fields_default_blank` to assert `plisio_secret_key == ""` and `plisio_pay_currency_list == ["LTC", "TON", "USDT_TON", "USDT_TRX", "TRX"]`.

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_plisio_client.py -q`
Expected: FAIL with `ModuleNotFoundError: app.services.payments.plisio`.

- [ ] **Step 3: Swap the config**

In `app/config.py`, delete the whole NOWPayments block (`nowpayments_api_key` through `nowpayments_settlement_currency`) and the `nowpayments_pay_currency_list` property, then add in their place:

```python
    # Plisio - ONE secret key authenticates API calls AND signs callbacks;
    # there is no separate IPN secret. create_crypto_payment raises
    # PaymentProviderNotConfiguredError while this is blank, so the bot
    # runs with crypto visibly unavailable until a key is provisioned.
    plisio_secret_key: str = ""

    # Full public URL Plisio POSTs invoice updates to. MUST carry
    # ?json=true: without it Plisio sends a PHP-serialized form post whose
    # verify_hash this app cannot reproduce - see the migration spec §3.
    plisio_callback_url: str = ""

    # Coins the buyer may pay with, as Plisio currency IDs (the ID column
    # of Plisio's Supported cryptocurrencies table), sent as
    # allowed_psys_cids so the buyer picks one on Plisio's invoice page.
    # Each must also have a wallet configured on the Plisio account.
    plisio_pay_currencies: str = "LTC,TON,USDT_TON,USDT_TRX,TRX"
```

and beside the other properties:

```python
    @property
    def plisio_pay_currency_list(self) -> list[str]:
        return [code.strip().upper() for code in self.plisio_pay_currencies.split(",") if code.strip()]
```

- [ ] **Step 4: Write the client**

`app/services/payments/plisio.py`:

```python
"""Client for Plisio's invoice API.

Plisio is GET-only: every call is
`GET https://api.plisio.net/api/v1/<action>?api_key=<SECRET_KEY>` and
every response is JSON shaped {"status": "success"|"error", "data": ...},
so a failure can arrive with HTTP 200 and status="error" - check the body,
not just the status code.

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
            f"Plisio {action} returned non-JSON ({response.status_code}): {response.text[:200]}"
        ) from exc

    if not isinstance(body, dict) or body.get("status") != "success":
        data = body.get("data") if isinstance(body, dict) else None
        message = data.get("message") if isinstance(data, dict) else None
        code = data.get("code") if isinstance(data, dict) else None
        raise PlisioError(
            f"Plisio {action} failed (http {response.status_code}, code {code}): {message or response.text[:200]}"
        )
    return body.get("data")


async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
    """Create a USD-priced invoice. Returns (invoice_url, txn_id).

    No coin is locked: allowed_psys_cids names every coin this account
    accepts and the buyer picks one on Plisio's own page, switching
    freely if a coin doesn't suit them. That is why this integration
    needs no per-coin minimum pre-check (see the migration spec §4)."""
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

    The Node example (the one that applies to json=true callbacks, which
    is the only variant a non-PHP integration can verify) hashes the
    payload in its RECEIVED key order. The PHP example ksorts first. They
    disagree, and rejecting a genuine callback means a paying customer
    never gets their service, so both are accepted - each is still an
    HMAC under the secret, so this concedes nothing to an attacker."""
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
```

- [ ] **Step 5: Run the tests**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_plisio_client.py tests/unit/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/services/payments/plisio.py tests/functional/test_plisio_client.py tests/conftest.py tests/unit/test_config.py
git commit -m "feat: Plisio API client and configuration"
```

---

## Task 2: Provider, service, and deletion of the payability feature

**Files:**
- Modify: `app/services/payments/base.py`, `crypto_provider.py`, `service.py`
- Delete: `app/services/payments/nowpayments.py`, `minimums.py`, `currencies.py`, `tests/functional/test_payability.py`, `test_minimums.py`, `test_nowpayments_client.py`, `tests/unit/test_currencies.py`
- Test: `tests/functional/test_payments_service.py`

**Interfaces:**
- Consumes: Task 1's client.
- Produces: `PaymentProvider.create_invoice(self, *, order_id, amount_usd, description) -> tuple[str, str]`; `CryptoProvider.verify_webhook(raw_body, signature) -> WebhookEvent | None`; `service.create_crypto_payment(session, *, telegram_id, purpose, plan, vpn_user) -> Payment` (no `pay_currency`); `service.quote_amount` unchanged.

- [ ] **Step 1: Delete the NOWPayments-only modules and their tests**

```bash
git rm app/services/payments/nowpayments.py app/services/payments/minimums.py app/services/payments/currencies.py \
      tests/functional/test_nowpayments_client.py tests/functional/test_payability.py tests/functional/test_minimums.py \
      tests/unit/test_currencies.py
```

- [ ] **Step 2: Update the abstraction**

In `app/services/payments/base.py`: remove the `from app.services.payments.currencies import PayCurrency` import, the `PAYABLE`/`UNPAYABLE`/`UNAVAILABLE` constants, the whole `PayabilityReport` dataclass, and the `payable_currencies` abstract method. Restore `create_invoice` to:

```python
    @abstractmethod
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        """Returns (url to hand the buyer, provider's own payment id)."""
```

Keep `WebhookEvent` and `verify_webhook` exactly as they are.

- [ ] **Step 3: Rewrite `CryptoProvider`**

`app/services/payments/crypto_provider.py`:

```python
from __future__ import annotations

from decimal import Decimal

from app.services.payments import plisio
from app.services.payments.base import PaymentProvider, WebhookEvent


class CryptoProvider(PaymentProvider):
    """Plisio-backed crypto payments. The buyer chooses their coin on
    Plisio's own invoice page (see plisio.create_invoice), so nothing
    here needs to know about individual coins or their minimums."""

    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return await plisio.create_invoice(order_id=order_id, amount=amount_usd, description=description)

    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        """`signature` is accepted for interface compatibility and
        deliberately unused: Plisio carries its verify_hash INSIDE the
        body, not in a header (unlike NOWPayments' x-nowpayments-sig)."""
        payload = plisio.verify_callback(raw_body)
        if payload is None:
            return None

        order_id = payload.get("order_number")
        txn_id = payload.get("txn_id")
        status = payload.get("status")
        if not order_id or not txn_id or not status:
            return None

        amount = payload.get("amount")
        try:
            paid_amount = Decimal(str(amount)) if amount not in (None, "") else None
        except (ArithmeticError, ValueError):
            paid_amount = None

        return WebhookEvent(
            provider_payment_id=str(txn_id),
            order_id=str(order_id),
            raw_status=str(status),
            paid_amount=paid_amount,
        )
```

- [ ] **Step 4: Simplify the payments service**

In `app/services/payments/service.py`: drop the `PayabilityReport` import and the `check_payability` function; remove the `pay_currency` parameter from `create_crypto_payment` and from its `_provider.create_invoice(...)` call; change the stale comment that names NOWPayments to name Plisio. `Payment(provider=...)` uses the model default, which Task 4 flips to `"plisio"`.

- [ ] **Step 5: Update the service tests**

In `tests/functional/test_payments_service.py`: delete `test_payment_provider_is_abstract`'s reference to `payable_currencies` if present, remove `pay_currency="usdttrc20"` from every `create_crypto_payment(...)` call, and drop `pay_currency` from every `_fake_create_invoice` signature. In `test_crypto_provider_create_invoice_delegates_to_client`, patch `plisio.create_invoice` instead of `nowpayments.create_invoice` and drop the `pay_currency` assertion.

- [ ] **Step 6: Run**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_payments_service.py tests/functional/test_plisio_client.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A app/services/payments tests
git commit -m "refactor: Plisio-backed CryptoProvider, delete the per-coin payability feature"
```

---

## Task 3: Buy and Renew return to a direct invoice

**Files:**
- Modify: `app/bot/handlers/buy.py`, `app/bot/handlers/renew.py`, `app/i18n/texts.py`
- Delete: `app/bot/handlers/_payability.py`, `app/bot/keyboards/payability.py`
- Test: `tests/functional/test_buy_flow.py`, `test_renew_flow.py`, `test_i18n.py`

**Interfaces:**
- Consumes: `create_crypto_payment` without `pay_currency`.
- Produces: `buy:confirm:<plan_id>` and `renew:confirm:<vu>:<plan_id>` go straight to the payment link. `buy:pay:*` and `renew:pay:*` no longer exist.

- [ ] **Step 1: Update the flow tests first**

In `tests/functional/test_buy_flow.py`: delete `_patch_report` and every test that uses it (`test_buy_confirm_lists_only_payable_coins`, `test_buy_confirm_creates_no_payment_row`, `test_buy_confirm_unavailable_when_lookups_failed`, `test_buy_pay_rejects_a_coin_that_is_no_longer_payable`, `test_buy_pay_reoffers_the_chooser_when_nowpayments_rejects_the_coin`, `test_buy_confirm_shows_below_minimum_message`). Rename `test_buy_pay_creates_payment_and_shows_link` back to `test_buy_confirm_creates_payment_and_shows_link`, driving it with `buy:confirm:{plan_id}` and a fake whose signature is `(self, *, order_id, amount_usd, description)`. Point `test_buy_confirm_shows_unavailable_message_on_api_error` at `plisio.PlisioError` raised from a patched `plisio.create_invoice`, fed by `buy:confirm:{plan_id}`. Do the same for `tests/functional/test_renew_flow.py` with `renew:confirm:{service.id}:{plan_id}`.

Add one test to each file proving no coin screen survives:

```python
@pytest.mark.asyncio
async def test_buy_confirm_goes_straight_to_the_payment_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plisio lets the buyer choose their coin on its own invoice page, so
    the bot must not interpose a coin chooser of its own."""
    from decimal import Decimal

    from app.services.payments.crypto_provider import CryptoProvider

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async def _fake_create_invoice(
        self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str
    ) -> tuple[str, str]:
        return "https://plisio.net/invoice/abc", "plisio-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b.get("url") == "https://plisio.net/invoice/abc" for b in buttons)
    assert not any((b.get("callback_data") or "").startswith("buy:pay:") for b in buttons)
```

In `tests/functional/test_i18n.py`, drop the key count by four (`91` becomes `87`).

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_buy_flow.py -q`
Expected: FAIL — the confirm handler still renders a chooser.

- [ ] **Step 3: Delete the chooser modules**

```bash
git rm app/bot/handlers/_payability.py app/bot/keyboards/payability.py
```

- [ ] **Step 4: Rewrite `buy_confirm_cb`**

In `app/bot/handlers/buy.py`, drop the imports of `render_payability`, `find_currency`, `invalidate`, `check_payability`, and `PaymentBelowMinimumError`; import `from app.services.payments.plisio import PaymentProviderNotConfiguredError, PlisioError`. Delete `buy_pay_cb` entirely and replace `buy_confirm_cb` with:

```python
@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    plan_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="purchase", plan=plan, vpn_user=None,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        except PlisioError:
            logger.error("Plisio invoice creation failed for plan %s", plan_id, exc_info=True)
            if callback.message is not None:
                await callback.message.edit_text(t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

    if callback.message is not None:
        await callback.message.edit_text(
            t("payment_link_heading", lang), reply_markup=payment_link_keyboard(payment.invoice_url, lang)
        )
    await callback.answer()
```

`quote_amount` is no longer imported here; the price summary screen keeps using its own `_price_summary_text`.

- [ ] **Step 5: Mirror it in `renew.py`**

Delete `renew_pay_cb`; restore `renew_confirm_cb` to its pre-chooser shape (keep the `_parse_id`/`_parse_int` guards, the `get_owned_vpn_user` ownership check, the `payment_coming_soon_renew` key, and the comment explaining that no renewal happens until the callback reports payment), with `PlisioError` in place of `NowPaymentsError` and no `PaymentBelowMinimumError` branch.

- [ ] **Step 6: Remove the dead i18n keys**

Delete `choose_pay_currency`, `payment_currency_changed`, `payment_below_minimum` and `back_to_plans_button` from both the `en` and `fa` blocks of `app/i18n/texts.py`.

- [ ] **Step 7: Run**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_buy_flow.py tests/functional/test_renew_flow.py tests/functional/test_i18n.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A app tests
git commit -m "feat: Buy and Renew create a Plisio invoice directly, no coin chooser"
```

---

## Task 4: Webhook status mapping

**Files:**
- Modify: `app/webhook.py`, `app/db/models/payment.py`, `app/db/models/payment_status_event.py`
- Test: `tests/functional/test_webhook.py`

**Interfaces:**
- Consumes: `CryptoProvider.verify_webhook`.
- Produces: the status table in spec §7.

- [ ] **Step 1: Update the webhook tests**

In `tests/functional/test_webhook.py`, replace the NOWPayments signing helper with a Plisio one:

```python
def _plisio_body(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    """A correctly signed Plisio callback: HMAC-SHA1 over the compact JSON
    body with verify_hash removed, keyed with PLISIO_SECRET_KEY."""
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings

    encoded = json_module.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    digest = hmac_module.new(
        get_settings().plisio_secret_key.encode(), encoded.encode(), hashlib.sha1
    ).hexdigest()
    body = json_module.dumps({**payload, "verify_hash": digest}, separators=(",", ":"), ensure_ascii=False).encode()
    return body, {"Content-Type": "application/json"}
```

Rewrite each existing webhook test's payload to Plisio's shape — `{"txn_id": ..., "order_number": str(payment.id), "status": ..., "amount": ...}` — with `completed` where tests used `finished`, and `expired` with an `amount` where they used `partially_paid`. Add:

```python
@pytest.mark.asyncio
async def test_cancelled_duplicate_never_fails_a_payment(...) -> None:
    """Plisio sets this on the abandoned invoice when a buyer switches
    coins; the replacement invoice is the one that completes. Failing the
    payment here would cancel an order the buyer is still paying."""
    # ... seed a pending payment, POST status="cancelled duplicate" ...
    # assert payment.status == "pending" and a PaymentStatusEvent row was written


@pytest.mark.asyncio
async def test_expired_with_no_amount_marks_the_payment_failed(...) -> None: ...


@pytest.mark.asyncio
async def test_expired_with_a_partial_amount_sends_the_topup_message(...) -> None: ...


@pytest.mark.asyncio
async def test_switching_coins_updates_the_stored_txn_id(...) -> None:
    """order_number stays ours across a coin switch, but txn_id changes -
    the newest one must win so the dashboard can be cross-referenced."""
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_webhook.py -q`
Expected: FAIL — the route still expects NOWPayments statuses.

- [ ] **Step 3: Update the route**

In `app/webhook.py`, replace the two status maps and their comments:

```python
# Plisio invoice statuses that reach a conclusion. Everything else
# ("new", "pending", "pending internal") is progress: logged as a
# PaymentStatusEvent, never changing Payment.status or notifying anyone.
#
# "cancelled duplicate" is deliberately absent: Plisio sets it on the
# invoice a buyer ABANDONED when they switched coins, while the
# replacement invoice (same order_number, new txn_id) is the one that
# completes. Treating it as a failure would cancel an order the buyer is
# still in the middle of paying.
_FINAL_STATUSES = {
    "completed": "paid",
    "expired": "expired",   # resolved below: partial payment or failure
    "cancelled": "failed",
    "error": "failed",
}

# Only these actually close a payment. "partially_paid" stays open: the
# buyer can still top up from the same invoice page, and a later
# "completed" callback for the same order must still be able to activate
# it.
_TERMINAL_STATUSES = {"paid", "failed", "refunded"}
```

Immediately after `new_status = _FINAL_STATUSES[event.raw_status]`, resolve `expired`:

```python
        if new_status == "expired":
            # Plisio has no "partially paid" status. Its docs say of an
            # expired invoice: "look for the amount field to verify
            # payment. The full amount may not have been paid." So a
            # non-zero received amount is this platform's partial
            # payment, and the existing top-up flow applies unchanged.
            new_status = "partially_paid" if (event.paid_amount or 0) > 0 else "failed"
```

Keep the `paid`, `partially_paid` and failure branches exactly as they are. Before the status branches, refresh the stored provider id so a coin switch is traceable:

```python
        # A buyer who switches coins gets a NEW Plisio invoice while
        # order_number stays ours, so the newest txn_id is the one that
        # matches the dashboard.
        if event.provider_payment_id and payment.provider_payment_id != event.provider_payment_id:
            payment.provider_payment_id = event.provider_payment_id
```

Change `_provider.verify_webhook(raw_body, signature)` to read the hash from the body: keep the call shape but source `signature` as `request.headers.get("x-plisio-sig", "")` is wrong — instead pass an empty string and note why:

```python
    # Plisio puts its verify_hash inside the body, so there is no
    # signature header to read (NOWPayments used x-nowpayments-sig).
    event = _provider.verify_webhook(raw_body, "")
```

Update the "lets NOWPayments retry the IPN" comment to name Plisio.

- [ ] **Step 4: Update the model docstrings**

In `app/db/models/payment.py`: change `provider`'s default to `"plisio"` and rewrite the docstring's NOWPayments references to Plisio (raw statuses now `new`/`pending`/`completed`/`expired`/…), noting that `paid_amount` is in the invoice's chosen cryptocurrency. Same for `payment_status_event.py`'s docstring. No migration: the column default is Python-side, and existing rows keep `"nowpayments"`, which is historically accurate.

- [ ] **Step 5: Run**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_webhook.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/webhook.py app/db/models tests/functional/test_webhook.py
git commit -m "feat: map Plisio invoice statuses in the callback handler"
```

---

## Task 5: Admin screens

**Files:**
- Modify: `app/bot/handlers/admin_settings.py`, `app/bot/keyboards/admin.py`, `app/bot/keyboards/admin_settings.py`, `app/bot/keyboards/crypto_settlement.py`
- Test: `tests/functional/test_admin_settings.py`, `test_admin_crypto_settlement.py`

**Interfaces:**
- Produces: `adm:settings:coins` (Crypto Coins). `adm:settings:minimums*` is gone.

- [ ] **Step 1: Write the tests**

Replace the two Crypto Minimums tests in `tests/functional/test_admin_settings.py` with:

```python
@pytest.mark.asyncio
async def test_crypto_coins_screen_lists_configured_coins(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.bot.handlers import admin_settings

    async def _fake_list_currencies() -> list[dict[str, Any]]:
        return [
            {"cid": "LTC", "name": "Litecoin", "price_usd": "80.00", "min_sum_in": "0.001",
             "hidden": 0, "maintenance": False},
            {"cid": "TRX", "name": "Tron", "price_usd": "0.30", "min_sum_in": "10",
             "hidden": 1, "maintenance": True},
            {"cid": "BTC", "name": "Bitcoin", "price_usd": "60000", "min_sum_in": "0.0000001",
             "hidden": 0, "maintenance": False},
        ]

    monkeypatch.setattr(admin_settings, "list_currencies", _fake_list_currencies)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:coins"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "Litecoin" in text and "$0.08" in text          # 0.001 LTC x $80
    assert "Tron" in text and "maintenance" in text.lower()
    assert "Bitcoin" not in text, "only the coins we accept belong on this screen"


@pytest.mark.asyncio
async def test_crypto_coins_screen_reports_an_api_failure(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.bot.handlers import admin_settings
    from app.services.payments.plisio import PlisioError

    async def _boom() -> list[dict[str, Any]]:
        raise PlisioError("upstream 500")

    monkeypatch.setattr(admin_settings, "list_currencies", _boom)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:coins"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "upstream 500" in text


@pytest.mark.asyncio
async def test_non_full_admin_cannot_open_crypto_coins(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=745, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(745, "adm:settings:coins"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("crypto coins" in c[1].get("text", "").lower() for c in edited)
```

In `tests/functional/test_admin_crypto_settlement.py`, delete every test that monkeypatches `nowpayments.validate_payout_address` or asserts an invalid-address rejection, and keep/adjust the ones covering the status screen, the network chooser and saving. Add one test that saving an address performs no outbound API call, and update the expected network labels to `USDT_TRX` etc.

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_admin_settings.py -q -k coins`
Expected: FAIL (no such screen).

- [ ] **Step 3: Replace the minimums screen**

In `app/bot/handlers/admin_settings.py`: remove `from app.services.payments import nowpayments`, the `PaymentProviderNotConfiguredError` import from that module, the `minimums` import, `_minimum_line`, `_minimums_text`, `settings_minimums_cb` and `settings_minimums_refresh_cb`. Add `from app.services.payments.plisio import PaymentProviderNotConfiguredError, PlisioError, list_currencies` and:

```python
def _coin_line(row: dict[str, Any], ) -> str:
    """One coin's live state. English-only, like every adm:* screen."""
    name = html.escape(str(row.get("name") or row.get("cid") or "?"))
    cid = html.escape(str(row.get("cid") or "?"))
    try:
        price = Decimal(str(row.get("price_usd") or "0"))
        minimum = Decimal(str(row.get("min_sum_in") or "0"))
        min_usd = f"${minimum * price:.2f}"
    except (ArithmeticError, ValueError):
        min_usd = "unknown"
    flags = []
    if row.get("maintenance"):
        flags.append("maintenance")
    if str(row.get("hidden", "0")) not in ("0", "False", "false"):
        flags.append("not enabled on this account")
    suffix = f" — {', '.join(flags)}" if flags else ""
    return f"• <b>{name}</b> ({cid}): min {html.escape(str(row.get('min_sum_in') or '?'))} ≈ {min_usd}{suffix}"


async def _crypto_coins_text() -> str:
    accepted = get_settings().plisio_pay_currency_list
    try:
        rows = await list_currencies()
    except PaymentProviderNotConfiguredError:
        return "💱 <b>Crypto Coins</b>\n\nPlisio isn't configured yet (PLISIO_SECRET_KEY is blank)."
    except PlisioError as exc:
        logger.error("Plisio currencies lookup failed", exc_info=True)
        return f"💱 <b>Crypto Coins</b>\n\n⚠️ Couldn't reach Plisio: {html.escape(str(exc)[:300])}"

    by_cid = {str(row.get("cid")): row for row in rows}
    lines = [_coin_line(by_cid[cid]) if cid in by_cid else f"• <b>{html.escape(cid)}</b>: not offered by Plisio" for cid in accepted]
    return (
        "💱 <b>Crypto Coins</b>\n\n"
        "The coins buyers can choose on the Plisio invoice page, with Plisio's "
        "own live minimum per coin.\n\n" + "\n".join(lines)
    )


@router.callback_query(F.data == "adm:settings:coins")
async def settings_crypto_coins_cb(callback: CallbackQuery, state: FSMContext) -> None:
    # No inline permission check: this whole router is gated by IsFullAdmin.
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(await _crypto_coins_text(), reply_markup=back_to_settings_keyboard())
    await callback.answer()
```

Add `from app.config import get_settings` if absent, and `from typing import Any`.

- [ ] **Step 4: Update the settings menu and settlement screen**

In `app/bot/keyboards/admin.py`, change the `💱 Crypto Minimums` button to `builder.button(text="💱 Crypto Coins", callback_data="adm:settings:coins")`. Delete `crypto_minimums_keyboard` from `app/bot/keyboards/admin_settings.py`.

In `app/bot/keyboards/crypto_settlement.py`, replace `NETWORK_LABELS` with Plisio ids and refresh the comment:

```python
# The coins this Plisio account has wallets for - code -> display label.
# Plisio currency IDs, matching PLISIO_PAY_CURRENCIES.
NETWORK_LABELS: dict[str, str] = {
    "USDT_TRX": "USDT (TRC-20)",
    "USDT_TON": "USDT (TON)",
    "TON": "TON",
    "TRX": "TRX",
    "LTC": "LTC",
}
```

and change `builder.adjust(2, 2, 1)` to `builder.adjust(2, 2, 1, 1)` so five coins plus Back still lay out.

In `crypto_settlement_receive_address`, delete the whole `try/except` block that calls `validate_payout_address` and the `if not is_valid:` branch, so a non-empty address saves directly. Update `_crypto_settlement_status_text`'s body sentence to say "never wired into Plisio".

- [ ] **Step 5: Run**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_admin_settings.py tests/functional/test_admin_crypto_settlement.py tests/functional/test_admin_panel_root.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite, then commit**

Run: `make test` (or the fallback in Global Constraints)
Expected: all PASS.

```bash
git add -A app tests
git commit -m "feat: admin Crypto Coins screen, Plisio networks, no address validation"
```

---

## Task 6: Docs, deploy, live verification

**Files:**
- Modify: `CLAUDE.md`, `.env.example`, `.claude/skills/payment-provider-abstraction/SKILL.md`, headers of the two superseded specs

- [ ] **Step 1: Update the docs**

`.env.example`: drop the five `NOWPAYMENTS_*` lines, add

```
# Plisio - one secret key authenticates API calls AND signs callbacks
PLISIO_SECRET_KEY=
# MUST end with ?json=true or the callback signature cannot be verified
PLISIO_CALLBACK_URL=https://bot.alonet.co/webhooks/crypto?json=true
PLISIO_PAY_CURRENCIES=LTC,TON,USDT_TON,USDT_TRX,TRX
```

`CLAUDE.md`: replace the `app/services/payments/minimums.py` bullet with one describing `app/services/payments/plisio.py` — GET-only API, one secret for calls and callbacks, HMAC-SHA1 `verify_hash` inside the body, the `?json=true` requirement, `allowed_psys_cids` letting the buyer choose a coin on Plisio's page, and the standing rule that no per-coin minimum machinery belongs here.

`.claude/skills/payment-provider-abstraction/SKILL.md`: rewrite for Plisio. Keep the interface section (minus `payable_currencies`), replace the minimum-check sections with the callback-verification rules and the status table from spec §7, and keep the unchanged rules (blank key behaviour, commit-before-provider, single account-creation path).

Add to the top of `docs/superpowers/specs/2026-09-21-crypto-payability-design.md` and `…/2026-09-16-crypto-payment-design.md`:

```markdown
> **Superseded 2026-09-22** by `2026-09-22-plisio-migration-design.md`.
> Kept for the record of why the NOWPayments design looked like this.
```

```bash
git add -A CLAUDE.md .env.example .claude docs
git commit -m "docs: point the payments docs and skill at Plisio"
```

- [ ] **Step 2: STOP — ask for the key before anything live**

Ask the user for the Plisio secret key. Install it into `/home/peyman/Homeland-Bot/.env` on bot.alonet.co as `PLISIO_SECRET_KEY`, passing it over stdin so it never appears in a command line, and set `PLISIO_CALLBACK_URL=https://bot.alonet.co/webhooks/crypto?json=true` and `PLISIO_PAY_CURRENCIES=LTC,TON,USDT_TON,USDT_TRX,TRX`. Remove the five obsolete `NOWPAYMENTS_*` lines. Back up `.env` first, `chmod 600` after. Never print the value.

Tell the user to do two dashboard actions: register the server's IP under API settings (Request IP), and set the Status URL / callback to the `?json=true` URL.

- [ ] **Step 3: Deploy**

```bash
git push origin main
ssh homeland-bot-server 'cd ~/Homeland-Bot && git pull --ff-only && docker compose up -d --build && docker compose logs --tail=20 bot'
```

- [ ] **Step 4: Live verification**

1. Admin → Settings → Crypto Coins: the five coins appear with live minimums. Report any coin marked not enabled or in maintenance.
2. From inside the container, confirm `list_currencies()` returns the five and note each `min_sum_in` in USD against the cheapest active plan.
3. Buy a plan in the real bot: the invoice page opens and offers exactly those five coins.
4. Callback probes, as done for the NOWPayments migration: a forged body returns 401, and a correctly signed body for a nonexistent `order_number` returns "ignored" with no side effects.

---

## Self-Review

- **Spec coverage:** §2 transport → Task 1; §3 callback verification → Tasks 1 and 4; §4 deletions → Tasks 2 and 3; §5 config → Task 1; §6 client/provider/service → Tasks 1 and 2; §7 status map → Task 4; §8 admin screens → Task 5; §9 rollout → Task 6; §10 tests → Tasks 1–5; §11 docs → Task 6.
- **Placeholder scan:** the only prose-only steps are the mechanical test edits in Tasks 3–5 (delete named tests, rename a callback), each naming the exact tests and callbacks involved; every new behaviour carries real code.
- **Type consistency:** `create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]` returns `(invoice_url, txn_id)` in the client and is called that way by `CryptoProvider`, whose own `create_invoice(*, order_id, amount_usd, description)` matches `PaymentProvider` and every test fake. `verify_callback(raw_body: bytes) -> dict | None` matches its use in `verify_webhook`. `list_currencies() -> list[dict[str, Any]]` matches the admin screen and its fakes. `create_crypto_payment` takes no `pay_currency` in the service, both handlers, and all tests.
