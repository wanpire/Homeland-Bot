"""Live per-coin minimum payable amounts from NOWPayments, cached in
Redis so the purchase flow can answer "is this price payable in this
coin right now?" without calling the API on every button press.

NOWPayments publishes no rate limit; this cache bounds us to at most one
request per accepted coin per FRESH_SECONDS across the whole bot, with a
STALE_SECONDS fallback so a NOWPayments outage degrades to slightly old
numbers rather than blocking checkout.

No per-coin threshold is ever hardcoded here or anywhere else: every
number comes from GET /v1/min-amount at runtime, so minimums that drift
with network fees keep working with no code change."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

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
    if not currencies:
        return []

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
        logger.error(
            "Redis unavailable while reading NOWPayments minimums - falling back to live lookups", exc_info=True
        )

    now = time.time()
    refresh_codes = [
        currency.code
        for currency in currencies
        if force_refresh
        or cached[currency.code] is None
        or (now - cached[currency.code][1]) >= FRESH_SECONDS  # type: ignore[index]
    ]

    fetched: dict[str, Decimal | None] = {}
    if refresh_codes:
        results = await asyncio.gather(*(_fetch_one(code) for code in refresh_codes))
        for code, (value, error) in zip(refresh_codes, results):
            fetched[code] = value
            if error is not None:
                errors[code] = error
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
            # An entry we deliberately did not refresh is still fresh; one
            # we tried and failed to refresh is served as a stale fallback
            # rather than dropped, so a NOWPayments outage doesn't block
            # every purchase.
            state = STALE if code in refresh_codes else FRESH
            if state == STALE:
                logger.warning("Using stale NOWPayments minimum for %s (age %.0fs)", code, now - entry[1])
            out.append(CurrencyMinimum(currency, entry[0], entry[1], state, errors[code]))
            continue

        out.append(CurrencyMinimum(currency, None, None, UNKNOWN, errors[code]))
    return out


async def _fetch_one(code: str) -> tuple[Decimal | None, str | None]:
    """(minimum, error text). Never raises - one coin's failure must not
    take down the lookup for the others."""
    try:
        return await get_min_amount(currency_from=code), None
    except NowPaymentsError as exc:
        logger.error("NOWPayments min-amount lookup failed for %s: %s", code, exc)
        return None, str(exc)[:300]
    except Exception as exc:  # PaymentProviderNotConfiguredError, and anything unforeseen
        logger.error("NOWPayments min-amount lookup failed for %s: %s", code, exc)
        return None, str(exc)[:300]


async def _store(redis: Any, fetched: dict[str, Decimal | None], errors: dict[str, str | None]) -> None:
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
