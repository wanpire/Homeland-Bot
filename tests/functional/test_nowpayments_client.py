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


async def _noop_check_minimum_amount(amount_usd: Decimal) -> None:
    """create_invoice now calls check_minimum_amount before posting -
    every test below that isn't specifically about that check patches
    it out to a no-op, so it keeps testing only create_invoice's own
    behavior (the POST /invoice call), not min-amount lookups."""
    return None


@pytest.mark.asyncio
async def test_create_invoice_returns_url_and_payment_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-123"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(nowpayments, "check_minimum_amount", _noop_check_minimum_amount)

    invoice_url, payment_id = await nowpayments.create_invoice(
        order_id="42", amount=Decimal("5.00"), description="Homeland: 1 Month",
    )

    assert invoice_url == "https://nowpayments.io/payment/abc"
    assert payment_id == "np-123"
    assert captured["url"] == "https://api.nowpayments.io/v1/invoice"
    assert captured["json"]["order_id"] == "42"
    assert captured["json"]["price_amount"] == "5.00"
    assert captured["json"]["price_currency"] == "usd"
    assert captured["headers"]["x-api-key"] == "test-nowpayments-api-key"


@pytest.mark.asyncio
async def test_create_invoice_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import nowpayments

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")

    with pytest.raises(nowpayments.PaymentProviderNotConfiguredError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(500, text="internal error")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(nowpayments, "check_minimum_amount", _noop_check_minimum_amount)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_on_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc"})  # missing "id"

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(nowpayments, "check_minimum_amount", _noop_check_minimum_amount)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_nowpayments_error_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(nowpayments, "check_minimum_amount", _noop_check_minimum_amount)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_nowpayments_error_on_non_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    class _NonJsonResponse:
        status_code = 200
        text = "<html>not json</html>"
        def json(self) -> Any:
            raise ValueError("not valid JSON")

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]):
        return _NonJsonResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(nowpayments, "check_minimum_amount", _noop_check_minimum_amount)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_includes_optional_callback_and_success_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import nowpayments

    monkeypatch.setattr(get_settings(), "nowpayments_ipn_callback_url", "https://bot.example.com/webhooks/crypto")
    monkeypatch.setattr(get_settings(), "bot_username", "homelandservice_bot")
    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-1"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(nowpayments, "check_minimum_amount", _noop_check_minimum_amount)

    await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")

    assert captured["json"]["ipn_callback_url"] == "https://bot.example.com/webhooks/crypto"
    assert captured["json"]["success_url"] == "https://t.me/homelandservice_bot"
    assert captured["json"]["cancel_url"] == "https://t.me/homelandservice_bot"


@pytest.mark.asyncio
async def test_create_invoice_omits_optional_urls_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-1"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(nowpayments, "check_minimum_amount", _noop_check_minimum_amount)

    await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")

    assert "ipn_callback_url" not in captured["json"]
    assert "success_url" not in captured["json"]
    assert "cancel_url" not in captured["json"]


def test_verify_ipn_signature_accepts_correctly_signed_payload() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.services.payments import nowpayments

    payload = {"order_id": "42", "payment_status": "finished"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac_module.new(b"test-secret", canonical.encode(), hashlib.sha512).hexdigest()

    assert nowpayments.verify_ipn_signature(raw_body, signature, "test-secret") is True


def test_verify_ipn_signature_rejects_wrong_secret() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.services.payments import nowpayments

    payload = {"order_id": "42"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac_module.new(b"right-secret", canonical.encode(), hashlib.sha512).hexdigest()

    assert nowpayments.verify_ipn_signature(raw_body, signature, "wrong-secret") is False


def test_verify_ipn_signature_rejects_empty_signature() -> None:
    from app.services.payments import nowpayments

    assert nowpayments.verify_ipn_signature(b'{"a": 1}', "", "secret") is False


def test_verify_ipn_signature_rejects_malformed_json() -> None:
    from app.services.payments import nowpayments

    assert nowpayments.verify_ipn_signature(b"not json", "abc123", "secret") is False


@pytest.mark.asyncio
async def test_get_min_amount_returns_fiat_equivalent_not_min_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two fields are NOT interchangeable - min_amount is in the
    crypto's own units (e.g. LTC), fiat_equivalent is USD. This must
    read fiat_equivalent."""
    from app.services.payments import nowpayments

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"currency_from": "ltc", "currency_to": "usd", "min_amount": 0.21, "fiat_equivalent": 12.08})

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    result = await nowpayments.get_min_amount(currency_from="ltc")

    assert result == Decimal("12.08")


@pytest.mark.asyncio
async def test_get_min_amount_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import nowpayments

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")

    with pytest.raises(nowpayments.PaymentProviderNotConfiguredError):
        await nowpayments.get_min_amount(currency_from="ltc")


@pytest.mark.asyncio
async def test_get_min_amount_raises_nowpayments_error_on_non_numeric_fiat_equivalent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed fiat_equivalent must surface as NowPaymentsError (which
    check_minimum_amount's _min_or_none already knows to swallow and fail
    open on) - not a raw decimal.InvalidOperation that would propagate
    uncaught and turn a fail-open scenario into a crash."""
    from app.services.payments import nowpayments

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"currency_from": "ltc", "currency_to": "usd", "min_amount": 0.21, "fiat_equivalent": "N/A"})

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.get_min_amount(currency_from="ltc")


@pytest.mark.asyncio
async def test_check_minimum_amount_fails_open_on_non_numeric_fiat_equivalent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"currency_from": params["currency_from"], "currency_to": "usd", "min_amount": 1, "fiat_equivalent": "N/A"})

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    await nowpayments.check_minimum_amount(Decimal("3.00"))  # no raise - every lookup failed to parse, so fail open


@pytest.mark.asyncio
async def test_get_min_amount_raises_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(404, text='{"message":"Currency not found"}')

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.get_min_amount(currency_from="bogus")


@pytest.mark.asyncio
async def test_check_minimum_amount_passes_when_amount_clears_every_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_min(*, currency_from: str, currency_to: str = "usd") -> Decimal:
        return Decimal("5.00")

    monkeypatch.setattr(nowpayments, "get_min_amount", _fake_min)

    await nowpayments.check_minimum_amount(Decimal("29.00"))  # no raise


@pytest.mark.asyncio
async def test_check_minimum_amount_passes_when_amount_clears_at_least_one_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only one of the 4 accepted coins needs to clear the bar - the
    customer can still pick that coin on NOWPayments' hosted page."""
    from app.services.payments import nowpayments

    async def _fake_min(*, currency_from: str, currency_to: str = "usd") -> Decimal:
        return Decimal("2.00") if currency_from == "ltc" else Decimal("12.00")

    monkeypatch.setattr(nowpayments, "get_min_amount", _fake_min)

    await nowpayments.check_minimum_amount(Decimal("5.00"))  # no raise - clears ltc's minimum


@pytest.mark.asyncio
async def test_check_minimum_amount_raises_when_below_every_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_min(*, currency_from: str, currency_to: str = "usd") -> Decimal:
        return Decimal("11.52")

    monkeypatch.setattr(nowpayments, "get_min_amount", _fake_min)

    with pytest.raises(nowpayments.PaymentBelowMinimumError):
        await nowpayments.check_minimum_amount(Decimal("3.00"))


@pytest.mark.asyncio
async def test_check_minimum_amount_fails_open_when_every_lookup_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A NOWPayments outage on this one endpoint must never block a
    purchase create_invoice could still complete."""
    from app.services.payments import nowpayments

    async def _fake_min(*, currency_from: str, currency_to: str = "usd") -> Decimal:
        raise nowpayments.NowPaymentsError("simulated outage")

    monkeypatch.setattr(nowpayments, "get_min_amount", _fake_min)

    await nowpayments.check_minimum_amount(Decimal("3.00"))  # no raise


@pytest.mark.asyncio
async def test_check_minimum_amount_fails_open_when_some_lookups_error_and_rest_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even one unknown minimum (an errored lookup) is enough to avoid
    blocking - only a confirmed reject-by-every-known-minimum blocks."""
    from app.services.payments import nowpayments

    async def _fake_min(*, currency_from: str, currency_to: str = "usd") -> Decimal:
        if currency_from == "ltc":
            raise nowpayments.NowPaymentsError("simulated outage")
        return Decimal("11.52")

    monkeypatch.setattr(nowpayments, "get_min_amount", _fake_min)

    with pytest.raises(nowpayments.PaymentBelowMinimumError):
        await nowpayments.check_minimum_amount(Decimal("3.00"))


@pytest.mark.asyncio
async def test_create_invoice_raises_payment_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_check(amount_usd: Decimal) -> None:
        raise nowpayments.PaymentBelowMinimumError("too small")

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        raise AssertionError("must not POST /invoice when the amount is below minimum")

    monkeypatch.setattr(nowpayments, "check_minimum_amount", _fake_check)
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    with pytest.raises(nowpayments.PaymentBelowMinimumError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("3.00"), description="x")


@pytest.mark.asyncio
async def test_validate_payout_address_accepts_a_valid_address(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, text="OK")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    is_valid, error = await nowpayments.validate_payout_address(address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", currency="usdttrc20")

    assert is_valid is True
    assert error is None


@pytest.mark.asyncio
async def test_validate_payout_address_rejects_an_invalid_address(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(
            400,
            {"status": False, "statusCode": 400, "code": "BAD_ADDRESS_VALIDATION_REQUEST", "message": "Invalid payout address: USDTTRC20 bogus"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    is_valid, error = await nowpayments.validate_payout_address(address="bogus", currency="usdttrc20")

    assert is_valid is False
    assert error == "Invalid payout address: USDTTRC20 bogus"


@pytest.mark.asyncio
async def test_validate_payout_address_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import nowpayments

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")

    with pytest.raises(nowpayments.PaymentProviderNotConfiguredError):
        await nowpayments.validate_payout_address(address="x", currency="usdttrc20")


def test_verify_ipn_signature_rejects_blank_secret() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.services.payments import nowpayments

    payload = {"order_id": "42"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    # A signature computed with an empty-string key - what an attacker
    # could trivially reproduce if the real secret is still unconfigured.
    forged_signature = hmac_module.new(b"", canonical.encode(), hashlib.sha512).hexdigest()

    assert nowpayments.verify_ipn_signature(raw_body, forged_signature, "") is False
