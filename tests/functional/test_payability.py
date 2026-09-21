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
async def test_amount_exactly_at_the_minimum_is_payable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    _patch(monkeypatch, [_minimum("trx", "12.00")])
    report = await CryptoProvider().payable_currencies(Decimal("12.00"))

    assert [c.code for c in report.payable] == ["trx"]


@pytest.mark.asyncio
async def test_a_stale_minimum_still_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale value is a real number from NOWPayments, just older than the
    refresh window - far better than treating the coin as unknown and
    telling the buyer the provider is down."""
    from app.services.payments.minimums import STALE
    from app.services.payments.crypto_provider import CryptoProvider

    _patch(monkeypatch, [_minimum("trx", "4.00", STALE)])
    report = await CryptoProvider().payable_currencies(Decimal("5.00"))

    assert [c.code for c in report.payable] == ["trx"]
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
