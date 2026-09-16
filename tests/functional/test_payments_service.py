from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


def test_webhook_event_holds_expected_fields() -> None:
    from app.services.payments.base import WebhookEvent

    event = WebhookEvent(provider_payment_id="np-1", order_id="42", raw_status="finished", paid_amount=Decimal("5"))
    assert event.provider_payment_id == "np-1"
    assert event.order_id == "42"
    assert event.raw_status == "finished"
    assert event.paid_amount == Decimal("5")


def test_payment_provider_is_abstract() -> None:
    from app.services.payments.base import PaymentProvider

    with pytest.raises(TypeError):
        PaymentProvider()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_crypto_provider_create_invoice_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments
    from app.services.payments.crypto_provider import CryptoProvider

    async def _fake_create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
        assert order_id == "7"
        assert amount == Decimal("9.00")
        assert description == "Homeland: 2 Months"
        return "https://nowpayments.io/payment/xyz", "np-777"

    monkeypatch.setattr(nowpayments, "create_invoice", _fake_create_invoice)

    provider = CryptoProvider()
    url, payment_id = await provider.create_invoice(order_id="7", amount_usd=Decimal("9.00"), description="Homeland: 2 Months")
    assert url == "https://nowpayments.io/payment/xyz"
    assert payment_id == "np-777"


def test_crypto_provider_verify_webhook_returns_event_on_valid_signature() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings
    from app.services.payments.crypto_provider import CryptoProvider

    payload = {"order_id": "42", "payment_id": "np-1", "payment_status": "finished", "actually_paid": "5.0"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = get_settings().nowpayments_ipn_secret
    signature = hmac_module.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()

    event = CryptoProvider().verify_webhook(raw_body, signature)
    assert event is not None
    assert event.order_id == "42"
    assert event.provider_payment_id == "np-1"
    assert event.raw_status == "finished"
    assert event.paid_amount == Decimal("5.0")


def test_crypto_provider_verify_webhook_returns_none_on_invalid_signature() -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    event = CryptoProvider().verify_webhook(b'{"order_id": "1"}', "not-a-valid-signature")
    assert event is None


def test_crypto_provider_verify_webhook_returns_none_when_order_id_missing() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings
    from app.services.payments.crypto_provider import CryptoProvider

    payload = {"payment_id": "np-1", "payment_status": "finished"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = get_settings().nowpayments_ipn_secret
    signature = hmac_module.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()

    assert CryptoProvider().verify_webhook(raw_body, signature) is None


def test_crypto_provider_verify_webhook_handles_missing_actually_paid() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings
    from app.services.payments.crypto_provider import CryptoProvider

    payload = {"order_id": "42", "payment_id": "np-1", "payment_status": "waiting"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = get_settings().nowpayments_ipn_secret
    signature = hmac_module.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()

    event = CryptoProvider().verify_webhook(raw_body, signature)
    assert event is not None
    assert event.paid_amount is None
