from __future__ import annotations

from collections.abc import Generator

import pytest


def _clear_settings_cache() -> None:
    from app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_settings() -> Generator[None, None, None]:
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
