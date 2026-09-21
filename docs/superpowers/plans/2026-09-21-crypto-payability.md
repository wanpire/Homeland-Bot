# Crypto Payability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop customers hitting a "network minimum is higher than the price" dead end by showing, before payment, only the coins whose live NOWPayments minimum currently accepts that plan's price, and locking the invoice to the chosen coin.

**Architecture:** A new `minimums` service fetches `GET /v1/min-amount` per accepted coin and caches each result in Redis for 10 minutes (6-hour stale fallback), bounding API calls to at most one per coin per window. `PaymentProvider` gains `payable_currencies()` returning a `PayabilityReport`, and `create_invoice` gains an optional `pay_currency`. Buy and Renew render a shared coin chooser, an unpayable message, or an unavailable message from that report.

**Tech Stack:** Python 3.12, aiogram 3.x, httpx, redis.asyncio, SQLAlchemy 2.0 async, pytest in the isolated Docker stack (`make test`).

**Spec:** `docs/superpowers/specs/2026-09-21-crypto-payability-design.md`

## Global Constraints

- No hardcoded per-coin minimum anywhere. Every minimum comes from `GET /v1/min-amount` at runtime.
- Accepted coins come from `Settings.nowpayments_pay_currency_list` (default `"usdttrc20,usdtbsc,trx,ltc"`), never a literal list in handler or service code.
- Async only, type hints on every signature, handlers stay thin (parse, call service, render).
- Customer-facing strings go through `t(key, lang)` in both `fa` and `en`. Admin-facing strings (the `adm:*` screens) stay English and never go through `t()`.
- Never log or echo the API key. Log NOWPayments failures with coin, status and body excerpt at `logger.error`.
- Do not touch `app/webhook.py`, partial-payment handling, the `Payment` model, or any IBSng/account-creation path.
- Every new screen has a Back button; every handler that navigates away clears FSM state if it set any (this feature sets none).
- Redis access goes through `app/redis.py`'s `get_redis()`.
- Run the suite with `make test`. If the Docker image build hangs on this machine, start the stack with `docker compose -f docker-compose.test.yml -p homeland_bot_test up -d --no-build`, sync the tree with `tar --exclude=.git --exclude=.claude -cf - app tests alembic alembic.ini pytest.ini requirements*.txt | docker exec -i homeland_bot_test-test-runner-1 tar -xf - -C /app`, then `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/ -q`.

---

## File Structure

- **Modify** `app/config.py` — `nowpayments_pay_currencies` + `nowpayments_pay_currency_list`.
- **Create** `app/services/payments/currencies.py` — `PayCurrency`, `accepted_currencies()`, `find_currency()`.
- **Create** `app/services/payments/minimums.py` — `CurrencyMinimum`, `get_minimums()`, `invalidate()`.
- **Modify** `app/services/payments/nowpayments.py` — drop `currency_to`, remove `check_minimum_amount`, add `pay_currency`, map below-minimum 400s.
- **Modify** `app/services/payments/base.py` — `PayabilityReport`, two abstract-method signature changes.
- **Modify** `app/services/payments/crypto_provider.py` — implement `payable_currencies`, forward `pay_currency`.
- **Modify** `app/services/payments/service.py` — `quote_amount`, `check_payability`, `create_crypto_payment(pay_currency=...)`.
- **Create** `app/bot/keyboards/payability.py` — `pay_currency_keyboard`, `below_minimum_keyboard`.
- **Create** `app/bot/handlers/_payability.py` — `render_payability` shared by Buy and Renew.
- **Modify** `app/bot/handlers/buy.py`, `app/bot/handlers/renew.py` — confirm renders the report; new `:pay:` handlers.
- **Modify** `app/i18n/texts.py` — four keys in `en` and `fa`.
- **Modify** `app/bot/handlers/admin_settings.py`, `app/bot/keyboards/admin.py` — Crypto Minimums screen.
- **Create** `tests/unit/test_currencies.py`, `tests/functional/test_minimums.py`, `tests/functional/test_payability.py`.
- **Modify** `tests/functional/test_nowpayments_client.py`, `test_buy_flow.py`, `test_renew_flow.py`, `test_admin_settings.py`, `tests/unit/test_config.py`.

---

## Task 1: Config + currency registry

**Files:**
- Modify: `app/config.py`
- Create: `app/services/payments/currencies.py`
- Test: `tests/unit/test_currencies.py`

**Interfaces:**
- Produces: `Settings.nowpayments_pay_currencies: str`, `Settings.nowpayments_pay_currency_list -> list[str]`, `PayCurrency(code: str, label: str)`, `accepted_currencies() -> list[PayCurrency]`, `find_currency(code: str) -> PayCurrency | None`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_currencies.py`:

```python
from __future__ import annotations

import pytest


def _clear_settings_cache() -> None:
    from app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_settings():  # type: ignore[no-untyped-def]
    _clear_settings_cache()
    yield
    _clear_settings_cache()


def test_default_currencies_are_the_four_dashboard_coins() -> None:
    from app.services.payments.currencies import accepted_currencies

    assert [c.code for c in accepted_currencies()] == ["usdttrc20", "usdtbsc", "trx", "ltc"]


def test_labels_are_human_readable() -> None:
    from app.services.payments.currencies import accepted_currencies

    labels = {c.code: c.label for c in accepted_currencies()}
    assert labels["usdttrc20"] == "USDT (TRC-20)"
    assert labels["usdtbsc"] == "USDT (BEP-20)"


def test_settings_order_is_honoured_and_unknown_codes_get_a_fallback_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOWPAYMENTS_PAY_CURRENCIES", "ton, ltc ,brandnewcoin")
    _clear_settings_cache()
    from app.services.payments.currencies import accepted_currencies

    coins = accepted_currencies()
    assert [c.code for c in coins] == ["ton", "ltc", "brandnewcoin"]
    assert coins[0].label == "TON"
    assert coins[2].label == "BRANDNEWCOIN"


def test_find_currency_is_case_insensitive_and_returns_none_for_unaccepted() -> None:
    from app.services.payments.currencies import find_currency

    assert find_currency("USDTTRC20") is not None
    assert find_currency("doge") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/unit/test_currencies.py -q`
Expected: FAIL with `ModuleNotFoundError: app.services.payments.currencies`.

- [ ] **Step 3: Add the setting**

In `app/config.py`, after `nowpayments_ipn_callback_url`:

```python
    # Coins a customer may pay with, as NOWPayments currency codes, in the
    # order the payment chooser lists them. Each must also be enabled in
    # the NOWPayments dashboard's coin settings. Extend here (e.g. add
    # ",ton") - never hardcode a per-coin minimum anywhere: minimums come
    # live from GET /v1/min-amount, see app/services/payments/minimums.py.
    nowpayments_pay_currencies: str = "usdttrc20,usdtbsc,trx,ltc"
```

and next to the other properties:

```python
    @property
    def nowpayments_pay_currency_list(self) -> list[str]:
        return [code.strip().lower() for code in self.nowpayments_pay_currencies.split(",") if code.strip()]
```

- [ ] **Step 4: Create the registry**

`app/services/payments/currencies.py`:

```python
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
    return [PayCurrency(code=code, label=_LABELS.get(code, code.upper())) for code in get_settings().nowpayments_pay_currency_list]


def find_currency(code: str) -> PayCurrency | None:
    """None for any code not currently accepted - callers use this to
    reject a stale keyboard's coin rather than trusting callback data."""
    wanted = code.strip().lower()
    return next((currency for currency in accepted_currencies() if currency.code == wanted), None)
```

- [ ] **Step 5: Run the test, verify it passes**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/unit/test_currencies.py tests/unit/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/services/payments/currencies.py tests/unit/test_currencies.py
git commit -m "feat: settings-driven accepted-currency registry for crypto payments"
```

---

## Task 2: Minimums service with Redis cache

**Files:**
- Modify: `app/services/payments/nowpayments.py`
- Create: `app/services/payments/minimums.py`
- Test: `tests/functional/test_minimums.py`, `tests/functional/test_nowpayments_client.py`

**Interfaces:**
- Consumes: `accepted_currencies()`, `PayCurrency` (Task 1).
- Produces: `CurrencyMinimum(currency, min_usd, fetched_at, state, last_error)`, `async get_minimums(*, force_refresh: bool = False) -> list[CurrencyMinimum]`, `async invalidate(code: str) -> None`, `FRESH_SECONDS`, `STALE_SECONDS`. `nowpayments.get_min_amount(*, currency_from: str) -> Decimal` (no `currency_to`).

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_minimums.py`:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._json_data


def _fake_get_returning(values: dict[str, Any], calls: list[str]):  # type: ignore[no-untyped-def]
    async def _get(self: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        code = params["currency_from"]
        calls.append(code)
        value = values[code]
        if isinstance(value, int) and value >= 400:
            return _FakeResponse(value, text="upstream boom")
        return _FakeResponse(200, {"currency_from": code, "min_amount": 0.21, "fiat_equivalent": value})

    return _get


@pytest.mark.asyncio
async def test_fetches_every_coin_once_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _fake_get_returning({"usdttrc20": 12.08, "usdtbsc": 11.5, "trx": 10.0, "ltc": 12.5}, calls),
    )

    first = await minimums.get_minimums()
    assert {m.currency.code: m.min_usd for m in first} == {
        "usdttrc20": Decimal("12.08"), "usdtbsc": Decimal("11.5"), "trx": Decimal("10.0"), "ltc": Decimal("12.5"),
    }
    assert all(m.state == "fresh" for m in first)
    assert sorted(calls) == ["ltc", "trx", "usdtbsc", "usdttrc20"]

    calls.clear()
    second = await minimums.get_minimums()
    assert calls == [], "a fresh cache entry must not hit the API again"
    assert {m.currency.code: m.min_usd for m in second} == {m.currency.code: m.min_usd for m in first}


@pytest.mark.asyncio
async def test_force_refresh_bypasses_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _fake_get_returning({"usdttrc20": 1, "usdtbsc": 1, "trx": 1, "ltc": 1}, calls),
    )
    await minimums.get_minimums()
    calls.clear()
    await minimums.get_minimums(force_refresh=True)
    assert sorted(calls) == ["ltc", "trx", "usdtbsc", "usdttrc20"]


@pytest.mark.asyncio
async def test_error_falls_back_to_the_stale_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get_returning({"usdttrc20": 12.08, "usdtbsc": 1, "trx": 1, "ltc": 1}, calls))
    await minimums.get_minimums()

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get_returning({"usdttrc20": 502, "usdtbsc": 1, "trx": 1, "ltc": 1}, calls))
    result = await minimums.get_minimums(force_refresh=True)

    trc = next(m for m in result if m.currency.code == "usdttrc20")
    assert trc.min_usd == Decimal("12.08")
    assert trc.state == "stale"
    assert trc.last_error and "502" in trc.last_error


@pytest.mark.asyncio
async def test_error_without_any_cached_value_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get_returning({"usdttrc20": 500, "usdtbsc": 500, "trx": 500, "ltc": 500}, calls))

    result = await minimums.get_minimums()
    assert all(m.state == "unknown" and m.min_usd is None for m in result)
    assert all(m.last_error for m in result)


@pytest.mark.asyncio
async def test_invalidate_forces_the_next_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get_returning({"usdttrc20": 5, "usdtbsc": 5, "trx": 5, "ltc": 5}, calls))
    await minimums.get_minimums()
    calls.clear()

    await minimums.invalidate("usdttrc20")
    await minimums.get_minimums()
    assert calls == ["usdttrc20"]
```

Append to `tests/functional/test_nowpayments_client.py`:

```python
@pytest.mark.asyncio
async def test_get_min_amount_omits_currency_to_so_the_dashboard_wallet_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """currency_to is deliberately absent: NOWPayments then computes the
    minimum against the outcome wallet configured in the dashboard
    (USDT TRC-20), which is the pair the invoice actually settles on."""
    from app.services.payments import nowpayments

    captured: dict[str, Any] = {}

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        captured["params"] = params
        return _FakeResponse(200, {"currency_from": "ltc", "min_amount": 0.21, "fiat_equivalent": 12.08})

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    assert await nowpayments.get_min_amount(currency_from="ltc") == Decimal("12.08")
    assert "currency_to" not in captured["params"]
    assert captured["params"]["fiat_equivalent"] == "usd"
```

Delete every existing `check_minimum_amount` test and the
`_noop_check_minimum_amount` monkeypatches (the function is removed in
Task 3; the chooser replaces it):
`test_check_minimum_amount_fails_open_on_non_numeric_fiat_equivalent`,
`test_check_minimum_amount_passes_when_amount_clears_every_currency`,
`test_check_minimum_amount_passes_when_amount_clears_at_least_one_currency`,
`test_check_minimum_amount_raises_when_below_every_currency`,
`test_check_minimum_amount_fails_open_when_every_lookup_errors`,
`test_check_minimum_amount_fails_open_when_some_lookups_error_and_rest_reject`,
`test_create_invoice_raises_payment_below_minimum`.

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_minimums.py -q`
Expected: FAIL with `ModuleNotFoundError: app.services.payments.minimums`.

- [ ] **Step 3: Update `get_min_amount`**

In `app/services/payments/nowpayments.py`, change the signature and params (leave the rest of the function as is):

```python
async def get_min_amount(*, currency_from: str) -> Decimal:
    """The minimum payable amount for currency_from in USD, via
    NOWPayments' own "fiat_equivalent" field - NOT "min_amount", which is
    denominated in currency_from's own units (e.g. "0.21" for LTC).
    Confirmed against the real API on 2026-09-18.

    currency_to is deliberately omitted: the docs state NOWPayments then
    calculates the minimum against the outcome currency configured in
    Payment Settings (Homeland's USDT TRC-20 wallet), which is the pair
    an invoice actually settles on."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    headers = {"x-api-key": settings.nowpayments_api_key}
    params = {"currency_from": currency_from, "fiat_equivalent": "usd"}
    ...unchanged from the try: onwards...
```

- [ ] **Step 4: Create the minimums service**

`app/services/payments/minimums.py`:

```python
"""Live per-coin minimum payable amounts from NOWPayments, cached in
Redis so the purchase flow can answer "is this price payable in this
coin right now?" without calling the API on every button press.

NOWPayments publishes no rate limit; this cache bounds us to at most one
request per accepted coin per FRESH_SECONDS across the whole bot, with a
STALE_SECONDS fallback so a NOWPayments outage degrades to slightly old
numbers rather than blocking checkout."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from redis.exceptions import RedisError

from app.redis import get_redis
from app.services.payments.currencies import PayCurrency, accepted_currencies
from app.services.payments.nowpayments import NowPaymentsError, get_min_amount

logger = logging.getLogger(__name__)

FRESH_SECONDS = 10 * 60
STALE_SECONDS = 6 * 60 * 60

_KEY = "homeland:npmin:{code}"
_ERR_KEY = "homeland:npmin:err:{code}"

FRESH = "fresh"
STALE = "stale"
UNKNOWN = "unknown"


@dataclass
class CurrencyMinimum:
    currency: PayCurrency
    min_usd: Decimal | None  # None only when state == UNKNOWN
    fetched_at: float | None
    state: str
    last_error: str | None

    @property
    def age_seconds(self) -> float | None:
        return None if self.fetched_at is None else max(0.0, time.time() - self.fetched_at)


def _parse_entry(raw: str | None) -> tuple[Decimal, float] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return Decimal(str(data["min_usd"])), float(data["fetched_at"])
    except (ValueError, KeyError, TypeError, InvalidOperation):
        return None


async def get_minimums(*, force_refresh: bool = False) -> list[CurrencyMinimum]:
    """One CurrencyMinimum per accepted coin, in Settings order. Never
    raises: a NOWPayments or Redis failure degrades to stale or unknown,
    which the caller renders rather than crashing the purchase flow."""
    currencies = accepted_currencies()
    cached: dict[str, tuple[Decimal, float] | None] = {currency.code: None for currency in currencies}
    errors: dict[str, str | None] = {currency.code: None for currency in currencies}

    redis = get_redis()
    try:
        keys = [_KEY.format(code=c.code) for c in currencies] + [_ERR_KEY.format(code=c.code) for c in currencies]
        raw_values = await redis.mget(keys)
        half = len(currencies)
        for index, currency in enumerate(currencies):
            cached[currency.code] = _parse_entry(raw_values[index])
            errors[currency.code] = raw_values[half + index]
    except RedisError:
        logger.error("Redis unavailable while reading NOWPayments minimums - falling back to live lookups", exc_info=True)

    now = time.time()
    stale_codes = [
        currency.code
        for currency in currencies
        if force_refresh or cached[currency.code] is None or (now - cached[currency.code][1]) >= FRESH_SECONDS
    ]

    fetched: dict[str, Decimal | None] = {}
    if stale_codes:
        results = await asyncio.gather(*(_fetch_one(code) for code in stale_codes))
        for code, (value, error) in zip(stale_codes, results):
            fetched[code] = value
            if error is not None:
                errors[code] = error

    if fetched:
        await _store(redis, fetched, errors)

    out: list[CurrencyMinimum] = []
    for currency in currencies:
        code = currency.code
        value = fetched.get(code)
        if value is not None:
            out.append(CurrencyMinimum(currency, value, time.time(), FRESH, None))
            continue
        entry = cached[code]
        if entry is not None:
            state = FRESH if (code not in stale_codes) else STALE
            out.append(CurrencyMinimum(currency, entry[0], entry[1], state, errors[code]))
            if state == STALE:
                logger.warning("Using stale NOWPayments minimum for %s (age %.0fs)", code, now - entry[1])
            continue
        out.append(CurrencyMinimum(currency, None, None, UNKNOWN, errors[code]))
    return out


async def _fetch_one(code: str) -> tuple[Decimal | None, str | None]:
    try:
        return await get_min_amount(currency_from=code), None
    except NowPaymentsError as exc:
        logger.error("NOWPayments min-amount lookup failed for %s: %s", code, exc)
        return None, str(exc)[:300]
    except Exception as exc:  # PaymentProviderNotConfiguredError and anything unexpected
        logger.error("NOWPayments min-amount lookup failed for %s: %s", code, exc)
        return None, str(exc)[:300]


async def _store(redis, fetched: dict[str, Decimal | None], errors: dict[str, str | None]) -> None:  # type: ignore[no-untyped-def]
    try:
        async with redis.pipeline(transaction=False) as pipe:
            for code, value in fetched.items():
                if value is not None:
                    pipe.set(
                        _KEY.format(code=code),
                        json.dumps({"min_usd": str(value), "fetched_at": time.time()}),
                        ex=STALE_SECONDS,
                    )
                    pipe.delete(_ERR_KEY.format(code=code))
                elif errors.get(code):
                    pipe.set(_ERR_KEY.format(code=code), errors[code], ex=STALE_SECONDS)
            await pipe.execute()
    except RedisError:
        logger.error("Redis unavailable while caching NOWPayments minimums", exc_info=True)


async def invalidate(code: str) -> None:
    """Drop one coin's cached minimum - called when NOWPayments rejects an
    invoice as below minimum despite our cache saying otherwise, so the
    next lookup re-fetches instead of repeating the same wrong answer."""
    try:
        await get_redis().delete(_KEY.format(code=code))
    except RedisError:
        logger.error("Redis unavailable while invalidating the cached minimum for %s", code, exc_info=True)
```

- [ ] **Step 5: Run the tests**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_minimums.py tests/functional/test_nowpayments_client.py -q`
Expected: PASS (the client file now has no `check_minimum_amount` tests).

- [ ] **Step 6: Commit**

```bash
git add app/services/payments/minimums.py app/services/payments/nowpayments.py tests/functional/test_minimums.py tests/functional/test_nowpayments_client.py
git commit -m "feat: Redis-cached per-coin NOWPayments minimum lookups"
```

---

## Task 3: Payability report, provider contract, payments service

**Files:**
- Modify: `app/services/payments/base.py`, `crypto_provider.py`, `service.py`, `nowpayments.py`
- Test: `tests/functional/test_payability.py`, `tests/functional/test_payments_service.py`, `tests/functional/test_nowpayments_client.py`

**Interfaces:**
- Consumes: `get_minimums` (Task 2), `PayCurrency` (Task 1).
- Produces: `PayabilityReport(payable, too_low, unknown)` with `.status` and `.lowest_minimum`; `PaymentProvider.payable_currencies(amount_usd)`; `create_invoice(..., pay_currency: str | None = None)`; `service.quote_amount(session, plan)`, `service.check_payability(amount_usd)`, `create_crypto_payment(..., pay_currency: str)`.

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_payability.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.payments.currencies import PayCurrency
from app.services.payments.minimums import FRESH, UNKNOWN, CurrencyMinimum


def _minimum(code: str, value: str | None, state: str = FRESH) -> CurrencyMinimum:
    return CurrencyMinimum(
        currency=PayCurrency(code=code, label=code.upper()),
        min_usd=None if value is None else Decimal(value),
        fetched_at=0.0 if value is not None else None,
        state=state,
        last_error=None if value is not None else "boom",
    )


def _patch(monkeypatch: pytest.MonkeyPatch, rows: list[CurrencyMinimum]) -> None:
    async def _fake_get_minimums(*, force_refresh: bool = False) -> list[CurrencyMinimum]:
        return rows

    from app.services.payments import crypto_provider

    monkeypatch.setattr(crypto_provider, "get_minimums", _fake_get_minimums)


@pytest.mark.asyncio
async def test_all_coins_payable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    _patch(monkeypatch, [_minimum("usdttrc20", "12.00"), _minimum("ltc", "11.00")])
    report = await CryptoProvider().payable_currencies(Decimal("20.00"))

    assert [c.code for c in report.payable] == ["usdttrc20", "ltc"]
    assert report.too_low == [] and report.unknown == []
    assert report.status == "payable"


@pytest.mark.asyncio
async def test_partially_payable_keeps_only_the_affordable_coins(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    _patch(monkeypatch, [_minimum("usdttrc20", "12.00"), _minimum("trx", "4.00"), _minimum("ltc", "11.00")])
    report = await CryptoProvider().payable_currencies(Decimal("5.00"))

    assert [c.code for c in report.payable] == ["trx"]
    assert [(c.code, str(m)) for c, m in report.too_low] == [("usdttrc20", "12.00"), ("ltc", "11.00")]
    assert report.status == "payable"


@pytest.mark.asyncio
async def test_fully_unpayable_reports_the_lowest_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    _patch(monkeypatch, [_minimum("usdttrc20", "12.00"), _minimum("ltc", "11.00")])
    report = await CryptoProvider().payable_currencies(Decimal("3.00"))

    assert report.payable == []
    assert report.status == "unpayable"
    assert report.lowest_minimum == Decimal("11.00")


@pytest.mark.asyncio
async def test_unknown_lookups_make_it_unavailable_not_unpayable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A NOWPayments outage must not tell the customer their plan is too
    cheap - that is a different message and a different remedy."""
    from app.services.payments.crypto_provider import CryptoProvider

    _patch(monkeypatch, [_minimum("usdttrc20", "12.00"), _minimum("ltc", None, UNKNOWN)])
    report = await CryptoProvider().payable_currencies(Decimal("3.00"))

    assert report.payable == []
    assert [c.code for c in report.unknown] == ["ltc"]
    assert report.status == "unavailable"
```

Append to `tests/functional/test_nowpayments_client.py`:

```python
@pytest.mark.asyncio
async def test_create_invoice_locks_the_chosen_pay_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-1"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await nowpayments.create_invoice(order_id="1", amount=Decimal("12.00"), description="x", pay_currency="ltc")
    assert captured["json"]["pay_currency"] == "ltc"


@pytest.mark.asyncio
async def test_create_invoice_omits_pay_currency_when_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-1"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await nowpayments.create_invoice(order_id="1", amount=Decimal("12.00"), description="x")
    assert "pay_currency" not in captured["json"]


@pytest.mark.asyncio
async def test_below_minimum_400_raises_payment_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOWPayments can still reject a locked invoice if the minimum moved
    inside our cache window - that must be recoverable (re-show the
    chooser), not a generic API error."""
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(400, text='{"message":"minimal amount for ltc is 0.21"}')

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    with pytest.raises(nowpayments.PaymentBelowMinimumError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("3.00"), description="x", pay_currency="ltc")


@pytest.mark.asyncio
async def test_other_400s_stay_generic_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(400, text='{"message":"invalid order_id"}')

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("30.00"), description="x", pay_currency="ltc")
```

In `tests/functional/test_payments_service.py`, update every
`create_invoice` fake signature to accept `pay_currency: str | None = None`
and every `create_crypto_payment(...)` call to pass
`pay_currency="usdttrc20"`.

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_payability.py -q`
Expected: FAIL — `CryptoProvider` has no `payable_currencies`.

- [ ] **Step 3: Add `PayabilityReport` and the contract**

In `app/services/payments/base.py`, add the import
`from app.services.payments.currencies import PayCurrency` and:

```python
PAYABLE = "payable"
UNPAYABLE = "unpayable"
UNAVAILABLE = "unavailable"


@dataclass
class PayabilityReport:
    """Which accepted coins can pay one exact USD amount right now.

    `unknown` exists to keep two very different failures apart: "your
    plan costs less than every network minimum" (the customer should buy
    a bigger plan) versus "we couldn't ask NOWPayments" (the customer
    should try again later)."""

    payable: list[PayCurrency]
    too_low: list[tuple[PayCurrency, Decimal]]
    unknown: list[PayCurrency]

    @property
    def status(self) -> str:
        if self.payable:
            return PAYABLE
        return UNAVAILABLE if self.unknown else UNPAYABLE

    @property
    def lowest_minimum(self) -> Decimal | None:
        return min((minimum for _, minimum in self.too_low), default=None)
```

and change the abstract methods:

```python
    @abstractmethod
    async def payable_currencies(self, amount_usd: Decimal) -> PayabilityReport:
        """Which accepted coins can pay this exact amount right now."""

    @abstractmethod
    async def create_invoice(
        self, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        """Returns (url to hand the buyer, provider's own payment id).
        pay_currency locks the hosted page to one coin."""
```

- [ ] **Step 4: Implement it in `CryptoProvider`**

`app/services/payments/crypto_provider.py` — add imports
`from app.services.payments.base import PayabilityReport, PaymentProvider, WebhookEvent`
and `from app.services.payments.minimums import get_minimums`, then:

```python
    async def payable_currencies(self, amount_usd: Decimal) -> PayabilityReport:
        payable, too_low, unknown = [], [], []
        for minimum in await get_minimums():
            if minimum.min_usd is None:
                unknown.append(minimum.currency)
            elif amount_usd >= minimum.min_usd:
                payable.append(minimum.currency)
            else:
                too_low.append((minimum.currency, minimum.min_usd))
        return PayabilityReport(payable=payable, too_low=too_low, unknown=unknown)

    async def create_invoice(
        self, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        return await nowpayments.create_invoice(
            order_id=order_id, amount=amount_usd, description=description, pay_currency=pay_currency
        )
```

- [ ] **Step 5: Update the NOWPayments client**

In `app/services/payments/nowpayments.py`: delete `check_minimum_amount`
entirely (and the now-unused `asyncio` import and
`_MIN_AMOUNT_CURRENCIES`), keep `PaymentBelowMinimumError` with an
updated docstring, then in `create_invoice`:

```python
async def create_invoice(
    *, order_id: str, amount: Decimal, description: str, pay_currency: str | None = None
) -> tuple[str, str]:
    """Returns (invoice_url, payment_id) - payment_id is NOWPayments'
    own id for this invoice, stored on Payment.provider_payment_id for
    IPN lookup. pay_currency locks the hosted page to one coin, so a
    customer can no longer pick a coin whose minimum exceeds the price;
    the caller picked it from a PayabilityReport."""
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
    ...unchanged optional urls/headers/post...

    if response.status_code >= 400:
        # A minimum can move between our cached lookup and this call.
        # That specific rejection is recoverable (drop the cache entry,
        # re-offer the chooser), so it gets its own exception type.
        if response.status_code == 400 and "min" in response.text.lower():
            raise PaymentBelowMinimumError(
                f"NOWPayments rejected {amount} USD in {pay_currency or 'any coin'} as below minimum: {response.text}"
            )
        raise NowPaymentsError(f"NOWPayments invoice creation failed: {response.status_code} {response.text}")
```

- [ ] **Step 6: Update the payments service**

In `app/services/payments/service.py`:

```python
async def quote_amount(session: AsyncSession, plan: Plan) -> tuple[Decimal, DiscountCode | None]:
    """The exact USD amount a buyer would pay for this plan right now,
    discounts included. The coin chooser and the invoice must price from
    this one function - a mismatch would offer a coin for one amount and
    then invoice a different one."""
    discount = await find_best_auto_discount(session, plan.id)
    amount = discount_price(plan.price_usd, discount.percent) if discount is not None else plan.price_usd
    return amount, discount


async def check_payability(amount_usd: Decimal) -> PayabilityReport:
    """Handlers call this, never the provider directly."""
    return await _provider.payable_currencies(amount_usd)
```

and in `create_crypto_payment`, add the required keyword and use the
helper:

```python
async def create_crypto_payment(
    session: AsyncSession,
    *,
    telegram_id: int,
    purpose: str,
    plan: Plan,
    vpn_user: VPNUser | None,
    pay_currency: str,
) -> Payment:
    amount, discount = await quote_amount(session, plan)
    ...unchanged Payment construction and commit...
    invoice_url, provider_payment_id = await _provider.create_invoice(
        order_id=str(payment.id), amount_usd=amount, description=f"Homeland: {plan.name}", pay_currency=pay_currency
    )
```

Add `from app.services.payments.base import PayabilityReport, PaymentProvider`.

- [ ] **Step 7: Run the tests**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_payability.py tests/functional/test_payments_service.py tests/functional/test_nowpayments_client.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/services/payments/ tests/functional/test_payability.py tests/functional/test_payments_service.py tests/functional/test_nowpayments_client.py
git commit -m "feat: per-coin payability report and pay_currency-locked invoices"
```

---

## Task 4: Coin chooser in Buy and Renew

**Files:**
- Create: `app/bot/keyboards/payability.py`, `app/bot/handlers/_payability.py`
- Modify: `app/i18n/texts.py`, `app/bot/handlers/buy.py`, `app/bot/handlers/renew.py`
- Test: `tests/functional/test_buy_flow.py`, `tests/functional/test_renew_flow.py`, `tests/functional/test_i18n.py`

**Interfaces:**
- Consumes: `check_payability`, `quote_amount`, `create_crypto_payment(pay_currency=...)`, `find_currency`, `minimums.invalidate`.
- Produces: callbacks `buy:pay:<plan_id>:<code>` and `renew:pay:<vpn_user_id>:<plan_id>:<code>`; `render_payability(...)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/functional/test_buy_flow.py`:

```python
def _patch_report(monkeypatch: pytest.MonkeyPatch, payable: list[str], too_low: list[tuple[str, str]], unknown: list[str]) -> None:
    from decimal import Decimal

    from app.services.payments.base import PayabilityReport
    from app.services.payments.currencies import PayCurrency

    async def _fake(amount_usd):  # type: ignore[no-untyped-def]
        return PayabilityReport(
            payable=[PayCurrency(code=c, label=c.upper()) for c in payable],
            too_low=[(PayCurrency(code=c, label=c.upper()), Decimal(m)) for c, m in too_low],
            unknown=[PayCurrency(code=c, label=c.upper()) for c in unknown],
        )

    from app.bot.handlers import buy as buy_handler

    monkeypatch.setattr(buy_handler, "check_payability", _fake)


@pytest.mark.asyncio
async def test_buy_confirm_lists_only_payable_coins(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=["trx"], too_low=[("usdttrc20", "12.00")], unknown=[])

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = {b["text"]: b.get("callback_data") for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert buttons["TRX"] == f"buy:pay:{plan_id}:trx"
    assert "USDTTRC20" not in buttons
    assert any("back" in text.lower() for text in buttons)


@pytest.mark.asyncio
async def test_buy_confirm_unpayable_names_the_lowest_minimum(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=[], too_low=[("usdttrc20", "12.00"), ("trx", "10.50")], unknown=[])

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "$10.50" in text and "too low" in text.lower()


@pytest.mark.asyncio
async def test_buy_confirm_unavailable_when_lookups_failed(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=[], too_low=[], unknown=["usdttrc20", "trx"])

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "couldn't reach the payment provider" in text.lower()


@pytest.mark.asyncio
async def test_buy_pay_creates_invoice_locked_to_the_chosen_coin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.services.payments.crypto_provider import CryptoProvider

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=["trx"], too_low=[], unknown=[])
    captured: dict[str, Any] = {}

    async def _fake_create_invoice(
        self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        captured["pay_currency"] = pay_currency
        return "https://nowpayments.io/payment/locked", "np-locked-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:pay:{plan_id}:trx"))

    assert captured["pay_currency"] == "trx"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "complete your payment" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_buy_pay_reoffers_the_chooser_when_nowpayments_rejects_the_coin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The minimum moved inside our cache window - the customer must get
    another coin to choose, never a dead end."""
    from decimal import Decimal

    from app.services.payments import nowpayments
    from app.services.payments.crypto_provider import CryptoProvider

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=["trx", "ltc"], too_low=[], unknown=[])
    invalidated: list[str] = []

    async def _reject(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None):
        raise nowpayments.PaymentBelowMinimumError("moved")

    async def _fake_invalidate(code: str) -> None:
        invalidated.append(code)

    monkeypatch.setattr(CryptoProvider, "create_invoice", _reject)
    from app.bot.handlers import buy as buy_handler

    monkeypatch.setattr(buy_handler, "invalidate", _fake_invalidate)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:pay:{plan_id}:trx"))

    assert invalidated == ["trx"]
    last = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]
    assert "pick another coin" in last["text"].lower()
    buttons = {b["text"] for row in last["reply_markup"]["inline_keyboard"] for b in row}
    assert "LTC" in buttons
```

Mirror all five in `tests/functional/test_renew_flow.py` with
`renew:confirm:<vu>:<plan_id>` / `renew:pay:<vu>:<plan_id>:<code>` and
`monkeypatch.setattr(renew_handler, ...)`. Update the existing
`test_buy_confirm_shows_below_minimum_message` and its renew twin to the
new report-driven path (they currently monkeypatch
`nowpayments.create_invoice`; point them at `_patch_report` with
everything `too_low`).

Add to `tests/functional/test_i18n.py` an assertion that each new key
exists in both languages (follow the file's existing parity test).

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_buy_flow.py -q`
Expected: FAIL — `buy` has no `check_payability` attribute.

- [ ] **Step 3: Add the i18n keys**

In `app/i18n/texts.py`, English block (near the other payment keys):

```python
        "choose_pay_currency": (
            "💱 <b>Choose a coin</b>\n\nPrice: {price}\n\n"
            "Pick the coin you'll pay with — only coins that currently accept "
            "this amount are shown:"
        ),
        "payment_below_minimum": (
            "⚠️ This plan's price is too low for a crypto payment right now — the "
            "lowest network minimum across the coins we accept is {min}. Please "
            "choose a higher-priced plan, or contact support."
        ),
        "payment_currency_changed": (
            "⚠️ That coin's minimum just changed and no longer accepts this amount. "
            "Please pick another coin."
        ),
        "back_to_plans_button": "⬅️ Back to Plans",
```

Persian block:

```python
        "choose_pay_currency": (
            "💱 <b>انتخاب ارز</b>\n\nقیمت: {price}\n\n"
            "ارزی که با آن پرداخت می‌کنید را انتخاب کنید — فقط ارزهایی نمایش داده "
            "می‌شوند که در حال حاضر این مبلغ را می‌پذیرند:"
        ),
        "payment_below_minimum": (
            "⚠️ قیمت این پلن برای پرداخت با ارز دیجیتال در حال حاضر خیلی پایین است — "
            "کمترین حداقل شبکه در میان ارزهای مورد پذیرش ما {min} است. لطفاً پلن با "
            "قیمت بالاتر انتخاب کنید یا با پشتیبانی تماس بگیرید."
        ),
        "payment_currency_changed": (
            "⚠️ حداقل مبلغ این ارز همین الان تغییر کرد و دیگر این مبلغ را نمی‌پذیرد. "
            "لطفاً ارز دیگری انتخاب کنید."
        ),
        "back_to_plans_button": "⬅️ بازگشت به پلن‌ها",
```

- [ ] **Step 4: Add the keyboards**

`app/bot/keyboards/payability.py`:

```python
"""Keyboards for the coin chooser and the below-minimum dead-end
replacement. Coin labels are proper nouns (USDT (TRC-20), TRX) and are
NOT translated; every other string here goes through t()."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t
from app.services.payments.currencies import PayCurrency


def pay_currency_keyboard(
    currencies: list[PayCurrency], *, pay_prefix: str, back_cb: str, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for currency in currencies:
        builder.button(text=currency.label, callback_data=f"{pay_prefix}:{currency.code}", style="success")
    builder.button(text=t("back_button", lang), callback_data=back_cb)
    builder.adjust(1)
    return builder.as_markup()


def below_minimum_keyboard(*, back_to_plans_cb: str, lang: str) -> InlineKeyboardMarkup:
    """Never a dead end: a customer told their plan is too cheap needs a
    one-tap route to a pricier one."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("back_to_plans_button", lang), callback_data=back_to_plans_cb)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Add the shared renderer**

`app/bot/handlers/_payability.py`:

```python
"""One renderer for the three payability outcomes, shared by Buy and
Renew so the two flows can never drift apart. Handlers stay thin: they
compute the amount and the report, then hand both to render_payability."""

from __future__ import annotations

from decimal import Decimal

from aiogram.types import CallbackQuery

from app.bot.keyboards.payability import below_minimum_keyboard, pay_currency_keyboard
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.i18n.texts import t
from app.services.catalog import format_price_usd
from app.services.payments.base import PAYABLE, UNAVAILABLE, PayabilityReport


async def render_payability(
    callback: CallbackQuery,
    report: PayabilityReport,
    amount: Decimal,
    lang: str,
    *,
    pay_prefix: str,
    back_to_summary_cb: str,
    back_to_plans_cb: str,
    notice: str | None = None,
) -> None:
    if callback.message is None:
        return

    if report.status == PAYABLE:
        text = t("choose_pay_currency", lang, price=format_price_usd(amount))
        if notice:
            text = f"{notice}\n\n{text}"
        await callback.message.edit_text(
            text,
            reply_markup=pay_currency_keyboard(
                report.payable, pay_prefix=pay_prefix, back_cb=back_to_summary_cb, lang=lang
            ),
        )
        return

    if report.status == UNAVAILABLE:
        await callback.message.edit_text(t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang))
        return

    minimum = report.lowest_minimum
    await callback.message.edit_text(
        t("payment_below_minimum", lang, min=format_price_usd(minimum) if minimum is not None else "—"),
        reply_markup=below_minimum_keyboard(back_to_plans_cb=back_to_plans_cb, lang=lang),
    )
```

- [ ] **Step 6: Rewrite `buy_confirm_cb` and add `buy_pay_cb`**

In `app/bot/handlers/buy.py`, replace the `create_crypto_payment` import
line with:

```python
from app.bot.handlers._payability import render_payability
from app.services.payments.currencies import find_currency
from app.services.payments.minimums import invalidate
from app.services.payments.service import check_payability, create_crypto_payment, quote_amount
```

then:

```python
@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        amount, _ = await quote_amount(session, plan)
        category = plan.category

    try:
        report = await check_payability(amount)
    except PaymentProviderNotConfiguredError:
        if callback.message is not None:
            await callback.message.edit_text(t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return

    await render_payability(
        callback, report, amount, lang,
        pay_prefix=f"buy:pay:{plan_id}",
        back_to_summary_cb=f"buy:plan:{plan_id}",
        back_to_plans_cb=f"buy:category:{category}",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:pay:"))
async def buy_pay_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    plan_id, code = int(parts[2]), parts[3]
    telegram_id = callback.from_user.id

    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        amount, _ = await quote_amount(session, plan)
        category = plan.category

        currency = find_currency(code)
        try:
            report = await check_payability(amount)
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        # A stale keyboard, or a minimum that moved since the chooser
        # rendered - re-offer whatever is payable now instead of sending
        # the buyer to an invoice that cannot be paid.
        if currency is None or currency.code not in {c.code for c in report.payable}:
            await render_payability(
                callback, report, amount, lang,
                pay_prefix=f"buy:pay:{plan_id}",
                back_to_summary_cb=f"buy:plan:{plan_id}",
                back_to_plans_cb=f"buy:category:{category}",
                notice=t("payment_currency_changed", lang),
            )
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="purchase", plan=plan, vpn_user=None, pay_currency=currency.code,
            )
        except PaymentBelowMinimumError:
            await invalidate(currency.code)
            refreshed = await check_payability(amount)
            await render_payability(
                callback, refreshed, amount, lang,
                pay_prefix=f"buy:pay:{plan_id}",
                back_to_summary_cb=f"buy:plan:{plan_id}",
                back_to_plans_cb=f"buy:category:{category}",
                notice=t("payment_currency_changed", lang),
            )
            await callback.answer()
            return
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error("NOWPayments invoice creation failed for plan %s in %s", plan_id, currency.code, exc_info=True)
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

Note the ordering constraint: `buy:pay:` must be registered before any
handler matching a broader `buy:p` prefix. There is none today
(`buy:plan:` is an exact-prefix match on a different string), so
registration order inside the router is unconstrained.

- [ ] **Step 7: Mirror it in `renew.py`**

Same structure in `renew_confirm_cb`, plus a new `renew_pay_cb` on
`F.data.startswith("renew:pay:")` parsing
`renew:pay:<vpn_user_id>:<plan_id>:<code>` with the existing
`_parse_id`/`_parse_int` guards and `get_owned_vpn_user` ownership check,
then `create_crypto_payment(..., purpose="renew", vpn_user=vpn_user, pay_currency=currency.code)`.
Navigation targets: `pay_prefix=f"renew:pay:{vpn_user_id}:{plan_id}"`,
`back_to_summary_cb=f"renew:plan:{vpn_user_id}:{plan_id}"`,
`back_to_plans_cb=f"renew:category:{vpn_user_id}:{category}"`. Keep the
`payment_coming_soon_renew` key for the unconfigured case.

- [ ] **Step 8: Run the full suite**

Run: `make test` (or the sync-and-run fallback from Global Constraints)
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add app/bot tests/functional/test_buy_flow.py tests/functional/test_renew_flow.py tests/functional/test_i18n.py app/i18n/texts.py
git commit -m "feat: in-bot coin chooser showing only currently payable coins"
```

---

## Task 5: Admin Crypto Minimums screen

**Files:**
- Modify: `app/bot/keyboards/admin.py`, `app/bot/handlers/admin_settings.py`
- Test: `tests/functional/test_admin_settings.py`

**Interfaces:**
- Consumes: `get_minimums(force_refresh=...)`, `CurrencyMinimum`.
- Produces: callbacks `adm:settings:minimums`, `adm:settings:minimums:refresh`.

- [ ] **Step 1: Write the failing test**

Append to `tests/functional/test_admin_settings.py`:

```python
@pytest.mark.asyncio
async def test_crypto_minimums_screen_lists_state_per_coin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decimal import Decimal

    from app.bot.handlers import admin_settings
    from app.services.payments.currencies import PayCurrency
    from app.services.payments.minimums import FRESH, UNKNOWN, CurrencyMinimum

    async def _fake_get_minimums(*, force_refresh: bool = False) -> list[CurrencyMinimum]:
        return [
            CurrencyMinimum(PayCurrency("usdttrc20", "USDT (TRC-20)"), Decimal("12.08"), 0.0, FRESH, None),
            CurrencyMinimum(PayCurrency("ltc", "LTC (Litecoin)"), None, None, UNKNOWN, "502 upstream"),
        ]

    monkeypatch.setattr(admin_settings, "get_minimums", _fake_get_minimums)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:minimums"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "USDT (TRC-20)" in text and "$12.08" in text and "fresh" in text
    assert "LTC (Litecoin)" in text and "unknown" in text and "502 upstream" in text


@pytest.mark.asyncio
async def test_crypto_minimums_refresh_forces_a_live_lookup(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.bot.handlers import admin_settings
    from app.services.payments.minimums import CurrencyMinimum

    forced: list[bool] = []

    async def _fake_get_minimums(*, force_refresh: bool = False) -> list[CurrencyMinimum]:
        forced.append(force_refresh)
        return []

    monkeypatch.setattr(admin_settings, "get_minimums", _fake_get_minimums)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:minimums:refresh"))

    assert forced == [True]
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_admin_settings.py -q -k minimums`
Expected: FAIL (the admin fallback answers with a permission alert, no screen renders).

- [ ] **Step 3: Add the menu entry**

In `app/bot/keyboards/admin.py`'s `admin_settings_menu()`, after the
Crypto Settlement Address button:

```python
    builder.button(text="💱 Crypto Minimums", callback_data="adm:settings:minimums")
```

- [ ] **Step 4: Add the handlers**

In `app/bot/handlers/admin_settings.py`, import
`from app.services.payments.minimums import FRESH, STALE, CurrencyMinimum, get_minimums`
and add:

```python
def _minimum_line(minimum: CurrencyMinimum) -> str:
    """One coin's status, English-only like every adm:* screen."""
    if minimum.min_usd is None:
        detail = f"unknown — last error: {html.escape(minimum.last_error)}" if minimum.last_error else "unknown"
        return f"• <b>{html.escape(minimum.currency.label)}</b>: {detail}"

    age = minimum.age_seconds or 0.0
    age_text = f"{age / 60:.0f} min ago" if age < 3600 else f"{age / 3600:.1f} h ago"
    line = f"• <b>{html.escape(minimum.currency.label)}</b>: ${minimum.min_usd} — {minimum.state}, {age_text}"
    if minimum.state == STALE and minimum.last_error:
        line += f"\n    last error: {html.escape(minimum.last_error)}"
    return line


async def _minimums_text(*, force_refresh: bool) -> str:
    rows = await get_minimums(force_refresh=force_refresh)
    body = "\n".join(_minimum_line(row) for row in rows) or "No pay currencies configured."
    return (
        "💱 <b>Crypto Minimums</b>\n\n"
        "Live NOWPayments minimum per accepted coin, cached for 10 minutes.\n"
        "A plan priced below a coin's minimum is hidden from that coin's buyers.\n\n" + body
    )


@router.callback_query(F.data == "adm:settings:minimums")
async def settings_minimums_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "full"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(await _minimums_text(force_refresh=False), reply_markup=crypto_minimums_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm:settings:minimums:refresh")
async def settings_minimums_refresh_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "full"):
            await callback.answer()
            return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(await _minimums_text(force_refresh=True), reply_markup=crypto_minimums_keyboard())
    await callback.answer("Refreshed from NOWPayments.")
```

Add to `app/bot/keyboards/admin_settings.py`:

```python
def crypto_minimums_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh now", callback_data="adm:settings:minimums:refresh")
    builder.button(text="⬅️ Back to Settings", callback_data="adm:settings")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/bot/handlers/admin_settings.py app/bot/keyboards/admin.py app/bot/keyboards/admin_settings.py tests/functional/test_admin_settings.py
git commit -m "feat: admin Crypto Minimums diagnostics screen"
```

---

## Task 6: Docs, deploy, live verification

**Files:**
- Modify: `CLAUDE.md`, `.env.example`, `.claude/skills/payment-provider-abstraction/SKILL.md`

- [ ] **Step 1: Document and commit**

`CLAUDE.md` Architecture: a bullet for `minimums.py` (the only place
that learns a coin's minimum, Redis-cached, no hardcoded thresholds) and
the coin chooser. `.env.example`: `NOWPAYMENTS_PAY_CURRENCIES=usdttrc20,usdtbsc,trx,ltc`.
The payment skill: the new `PaymentProvider` methods and the rule that a
price check must come from `check_payability`, never a literal.

```bash
git add CLAUDE.md .env.example .claude/skills/payment-provider-abstraction/SKILL.md
git commit -m "docs: note the payability check and pay-currency configuration"
```

- [ ] **Step 2: STOP — ask for credentials before anything live**

Ask the user for the new NOWPayments API key and IPN secret and have
them place the values in `/home/peyman/Homeland-Bot/.env` on
bot.alonet.co (`NOWPAYMENTS_API_KEY`, `NOWPAYMENTS_IPN_SECRET`). Do not
print, echo, log, or commit the values. Do not run any live check until
the user confirms they are in place.

- [ ] **Step 3: Deploy**

```bash
git push origin main
ssh homeland-bot-server 'cd ~/Homeland-Bot && git pull --ff-only && docker compose up -d --build && docker compose logs --tail=20 bot'
```

- [ ] **Step 4: Live verification (spec §10)**

1. Admin → Settings → Crypto Minimums → Refresh now: every coin `fresh`
   with a plausible USD figure. If a coin errors, read the last-error
   line and fix before continuing.
2. If the minimums look wrong or the call 400s, switch
   `get_min_amount` to pass `currency_to="usdttrc20"` and re-check.
3. Buy a low-priced plan: expect the below-minimum message naming the
   lowest minimum, with Back to Plans working.
4. Buy a plan above the minimum: chooser lists the payable coins; pick
   one, open the link, confirm the NOWPayments page is locked to that
   coin and shows an amount at or above its minimum.
5. Renew: repeat step 4 on an existing service.

---

## Self-Review

- **Spec coverage:** §3 config → Task 1; §4 registry → Task 1; §5 cache → Task 2; §6 report/provider/service → Task 3; §7 flow → Task 4; §8 i18n → Task 4 Step 3; §9 admin → Task 5; §10 live checks → Task 6; §11 tests → Tasks 1–5.
- **Placeholder scan:** none; every code step carries real code, and the one deliberate open question (whether `currency_to` may be omitted) has a stated fallback and a live check that decides it.
- **Type consistency:** `get_minimums(*, force_refresh: bool = False) -> list[CurrencyMinimum]` is used with that exact signature in the provider, the admin screen and every fake; `PayabilityReport(payable, too_low, unknown)` field names match between `base.py`, the provider, the renderer and the test helpers; `create_invoice(..., pay_currency: str | None = None)` matches across `base`, `crypto_provider`, `nowpayments` and every test fake; `create_crypto_payment(..., pay_currency: str)` is required in both handlers and both flow tests.
