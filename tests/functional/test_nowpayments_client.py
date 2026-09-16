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

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_on_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc"})  # missing "id"

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

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
