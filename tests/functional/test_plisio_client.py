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
async def test_create_invoice_raises_on_error_body_with_http_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """status="error" can arrive with HTTP 200 - the body is what counts."""
    from app.services.payments import plisio

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"status": "error", "data": {"message": "Invalid api_key", "code": 101}})

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(plisio.PlisioError):
        await plisio.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


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


@pytest.mark.asyncio
async def test_create_invoice_raises_on_non_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import plisio

    class _NonJson:
        status_code = 200
        text = "<html>nope</html>"

        def json(self) -> Any:
            raise ValueError("not JSON")

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]):
        return _NonJson()

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(plisio.PlisioError):
        await plisio.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


def test_verify_callback_accepts_received_key_order() -> None:
    from app.services.payments import plisio

    payload = {"txn_id": "abc", "order_number": "42", "status": "completed", "amount": "12.5"}
    result = plisio.verify_callback(_signed(payload))
    assert result is not None and result["status"] == "completed"


def test_verify_callback_accepts_sorted_key_order() -> None:
    """The docs' PHP example ksorts; the Node example does not. A genuine
    callback must not be rejected over that discrepancy - the customer
    would have paid and never received their service."""
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
    assert plisio.verify_callback(json.dumps(["not", "an", "object"]).encode()) is None


def test_verify_callback_returns_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import plisio

    body = _signed({"txn_id": "abc", "order_number": "42", "status": "completed"})
    monkeypatch.setattr(get_settings(), "plisio_secret_key", "")
    assert plisio.verify_callback(body) is None


def test_verify_callback_handles_non_ascii_values() -> None:
    """ensure_ascii=False matches JSON.stringify, which leaves non-ASCII
    characters unescaped - getting this wrong would break any callback
    carrying a non-Latin order name."""
    from app.services.payments import plisio

    payload = {"txn_id": "abc", "order_number": "42", "status": "completed", "order_name": "اشتراک"}
    assert plisio.verify_callback(_signed(payload)) is not None


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


@pytest.mark.asyncio
async def test_error_messages_never_leak_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plisio echoes api_key back inside the _links URLs of its own
    responses, so an error body quoted verbatim would write the secret
    into the logs."""
    from app.services.payments import plisio

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(400, {
            "status": "error",
            "data": {"message": f"bad request, see https://api.plisio.net/api/v1/operations?api_key={SECRET}"},
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(plisio.PlisioError) as excinfo:
        await plisio.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")
    assert SECRET not in str(excinfo.value)
    assert "***" in str(excinfo.value)


@pytest.mark.asyncio
async def test_non_json_error_also_redacts_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import plisio

    class _NonJson:
        status_code = 500
        text = f"gateway error for api_key={SECRET}"

        def json(self) -> Any:
            raise ValueError("not JSON")

    async def _fake_get(self: httpx.AsyncClient, url: str, *, params: dict[str, str]):
        return _NonJson()

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    with pytest.raises(plisio.PlisioError) as excinfo:
        await plisio.list_currencies()
    assert SECRET not in str(excinfo.value)
