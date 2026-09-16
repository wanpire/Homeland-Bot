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


@pytest.mark.asyncio
async def test_create_crypto_payment_purchase_creates_pending_row_with_invoice(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/abc", "np-999"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(
            session, telegram_id=950, purpose="purchase", plan=plan, vpn_user=None,
        )

    assert payment.id is not None
    assert payment.purpose == "purchase"
    assert payment.vpn_user_id is None
    assert payment.plan_id == plan_id
    assert payment.group_name == "1M-1U-Iran-10G"
    assert payment.data_cap_mb == 10240
    assert payment.amount_usd == Decimal("5.00")
    assert payment.original_amount_usd is None
    assert payment.invoice_url == "https://nowpayments.io/payment/abc"
    assert payment.provider_payment_id == "np-999"
    assert payment.status == "pending"
    assert payment.ibsng_username is not None
    assert payment.ibsng_password is not None


@pytest.mark.asyncio
async def test_create_crypto_payment_renew_targets_existing_service(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/renew", "np-1000"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    stream_plan_id = _plan_id(seeded_catalog, category="stream", name="1 Month")
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        existing = await create_vpn_user(
            session, client, telegram_id=951, username=username, password=password,
            group_name="1M-1U-Iran-10G", data_cap_mb=10240, plan_id=scroll_plan_id,
        )

    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        new_plan = await get_plan(session, stream_plan_id)
        payment = await create_crypto_payment(
            session, telegram_id=951, purpose="renew", plan=new_plan, vpn_user=existing,
        )

    assert payment.purpose == "renew"
    assert payment.vpn_user_id == existing.id
    assert payment.plan_id == stream_plan_id
    assert payment.ibsng_username is None
    assert payment.ibsng_password is None


@pytest.mark.asyncio
async def test_create_crypto_payment_applies_auto_discount(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.discounts import create_discount_code
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/disc", "np-1001"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        discount = await create_discount_code(
            session, code="TENOFF", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True,
        )

    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(
            session, telegram_id=952, purpose="purchase", plan=plan, vpn_user=None,
        )

    assert payment.amount_usd == Decimal("4.50")
    assert payment.original_amount_usd == Decimal("5.00")
    assert payment.discount_code_id == discount.id
