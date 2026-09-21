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
    async def _get(
        self: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]
    ) -> _FakeResponse:
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
        httpx.AsyncClient,
        "get",
        _fake_get_returning({"usdttrc20": 12.08, "usdtbsc": 11.5, "trx": 10.0, "ltc": 12.5}, calls),
    )

    first = await minimums.get_minimums()
    assert {m.currency.code: m.min_usd for m in first} == {
        "usdttrc20": Decimal("12.08"),
        "usdtbsc": Decimal("11.5"),
        "trx": Decimal("10.0"),
        "ltc": Decimal("12.5"),
    }
    assert all(m.state == "fresh" for m in first)
    assert sorted(calls) == ["ltc", "trx", "usdtbsc", "usdttrc20"]

    calls.clear()
    second = await minimums.get_minimums()
    assert calls == [], "a fresh cache entry must not hit the API again"
    assert {m.currency.code: m.min_usd for m in second} == {m.currency.code: m.min_usd for m in first}
    assert all(m.state == "fresh" for m in second)


@pytest.mark.asyncio
async def test_force_refresh_bypasses_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(
        httpx.AsyncClient, "get", _fake_get_returning({"usdttrc20": 1, "usdtbsc": 1, "trx": 1, "ltc": 1}, calls)
    )
    await minimums.get_minimums()
    calls.clear()
    await minimums.get_minimums(force_refresh=True)
    assert sorted(calls) == ["ltc", "trx", "usdtbsc", "usdttrc20"]


@pytest.mark.asyncio
async def test_error_falls_back_to_the_stale_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        _fake_get_returning({"usdttrc20": 12.08, "usdtbsc": 1, "trx": 1, "ltc": 1}, calls),
    )
    await minimums.get_minimums()

    monkeypatch.setattr(
        httpx.AsyncClient, "get", _fake_get_returning({"usdttrc20": 502, "usdtbsc": 1, "trx": 1, "ltc": 1}, calls)
    )
    result = await minimums.get_minimums(force_refresh=True)

    trc = next(m for m in result if m.currency.code == "usdttrc20")
    assert trc.min_usd == Decimal("12.08")
    assert trc.state == "stale"
    assert trc.last_error and "502" in trc.last_error


@pytest.mark.asyncio
async def test_error_without_any_cached_value_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        _fake_get_returning({"usdttrc20": 500, "usdtbsc": 500, "trx": 500, "ltc": 500}, calls),
    )

    result = await minimums.get_minimums()
    assert all(m.state == "unknown" and m.min_usd is None for m in result)
    assert all(m.last_error for m in result)


@pytest.mark.asyncio
async def test_invalidate_forces_the_next_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import minimums

    calls: list[str] = []
    monkeypatch.setattr(
        httpx.AsyncClient, "get", _fake_get_returning({"usdttrc20": 5, "usdtbsc": 5, "trx": 5, "ltc": 5}, calls)
    )
    await minimums.get_minimums()
    calls.clear()

    await minimums.invalidate("usdttrc20")
    await minimums.get_minimums()
    assert calls == ["usdttrc20"]
