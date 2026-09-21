from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


def test_webhook_event_holds_expected_fields() -> None:
    from app.services.payments.base import WebhookEvent

    event = WebhookEvent(provider_payment_id="plisio-1", order_id="42", raw_status="completed", paid_amount=Decimal("5"))
    assert event.provider_payment_id == "plisio-1"
    assert event.order_id == "42"
    assert event.raw_status == "completed"
    assert event.paid_amount == Decimal("5")


def test_payment_provider_is_abstract() -> None:
    from app.services.payments.base import PaymentProvider

    with pytest.raises(TypeError):
        PaymentProvider()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_crypto_provider_create_invoice_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import plisio
    from app.services.payments.crypto_provider import CryptoProvider

    async def _fake_create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
        assert order_id == "7"
        assert amount == Decimal("9.00")
        assert description == "Homeland: 2 Months"
        return "https://plisio.net/invoice/xyz", "plisio-777"

    monkeypatch.setattr(plisio, "create_invoice", _fake_create_invoice)

    provider = CryptoProvider()
    url, payment_id = await provider.create_invoice(
        order_id="7", amount_usd=Decimal("9.00"), description="Homeland: 2 Months"
    )
    assert url == "https://plisio.net/invoice/xyz"
    assert payment_id == "plisio-777"


def _plisio_callback(payload: dict[str, Any]) -> bytes:
    """A correctly signed Plisio callback body: HMAC-SHA1 over the compact
    JSON payload with verify_hash removed, keyed with PLISIO_SECRET_KEY.
    The hash travels inside the body - Plisio sends no signature header."""
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings

    encoded = json_module.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    digest = hmac_module.new(
        get_settings().plisio_secret_key.encode(), encoded.encode(), hashlib.sha1
    ).hexdigest()
    return json_module.dumps({**payload, "verify_hash": digest}, separators=(",", ":"), ensure_ascii=False).encode()


def test_crypto_provider_verify_webhook_returns_event_on_valid_callback() -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    body = _plisio_callback(
        {"txn_id": "plisio-1", "order_number": "42", "status": "completed", "amount": "5.0"}
    )

    event = CryptoProvider().verify_webhook(body, "")
    assert event is not None
    assert event.order_id == "42"
    assert event.provider_payment_id == "plisio-1"
    assert event.raw_status == "completed"
    assert event.paid_amount == Decimal("5.0")


def test_crypto_provider_verify_webhook_returns_none_on_invalid_hash() -> None:
    import json as json_module

    from app.services.payments.crypto_provider import CryptoProvider

    body = json_module.dumps({"txn_id": "x", "order_number": "1", "status": "completed", "verify_hash": "nope"}).encode()
    assert CryptoProvider().verify_webhook(body, "") is None


def test_crypto_provider_verify_webhook_returns_none_when_order_number_missing() -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    body = _plisio_callback({"txn_id": "plisio-1", "status": "completed"})
    assert CryptoProvider().verify_webhook(body, "") is None


def test_crypto_provider_verify_webhook_handles_missing_amount() -> None:
    """Progress callbacks ("new", "pending") carry no received amount."""
    from app.services.payments.crypto_provider import CryptoProvider

    body = _plisio_callback({"txn_id": "plisio-1", "order_number": "42", "status": "pending"})

    event = CryptoProvider().verify_webhook(body, "")
    assert event is not None
    assert event.paid_amount is None


def test_crypto_provider_verify_webhook_ignores_the_signature_argument() -> None:
    """Plisio has no signature header; the argument exists only to satisfy
    the PaymentProvider interface and must never affect the verdict."""
    from app.services.payments.crypto_provider import CryptoProvider

    body = _plisio_callback({"txn_id": "plisio-1", "order_number": "42", "status": "completed"})
    assert CryptoProvider().verify_webhook(body, "anything-at-all") is not None


@pytest.mark.asyncio
async def test_create_crypto_payment_purchase_creates_pending_row_with_invoice(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/abc", "plisio-999"

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
    assert payment.invoice_url == "https://plisio.net/invoice/abc"
    assert payment.provider_payment_id == "plisio-999"
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
        return "https://plisio.net/invoice/renew", "plisio-1000"

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
        return "https://plisio.net/invoice/disc", "np-1001"

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


@pytest.mark.asyncio
async def test_activate_finished_payment_purchase_creates_vpn_user(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.session import async_session_maker as make_session
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import activate_finished_payment, create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/act", "np-2000"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with make_session() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=960, purpose="purchase", plan=plan, vpn_user=None)

    async with make_session() as session, IBSngClient() as client:
        from sqlalchemy import select

        from app.db.models.payment import Payment

        payment = await session.get(Payment, payment.id)
        username = await activate_finished_payment(session, client, payment)
        await session.commit()

        from app.db.models.vpn_user import VPNUser

        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 960))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ibsng_username == username
    assert payment.vpn_user_id == rows[0].id


@pytest.mark.asyncio
async def test_activate_finished_payment_renew_updates_existing_service(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.session import async_session_maker as make_session
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import activate_finished_payment, create_crypto_payment
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/renew2", "np-2001"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    scroll_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    stream_id = _plan_id(seeded_catalog, category="stream", name="1 Month")
    username, password = generate_vpn_credentials()
    async with make_session() as session, IBSngClient() as client:
        existing = await create_vpn_user(
            session, client, telegram_id=961, username=username, password=password,
            group_name="1M-1U-Iran-10G", data_cap_mb=10240, plan_id=scroll_id,
        )

    async with make_session() as session:
        from app.services.catalog import get_plan

        new_plan = await get_plan(session, stream_id)
        payment = await create_crypto_payment(session, telegram_id=961, purpose="renew", plan=new_plan, vpn_user=existing)

    async with make_session() as session, IBSngClient() as client:
        from app.db.models.payment import Payment

        payment = await session.get(Payment, payment.id)
        returned_username = await activate_finished_payment(session, client, payment)
        await session.commit()

        from app.db.models.vpn_user import VPNUser

        refreshed = await session.get(VPNUser, existing.id)

    assert returned_username == existing.ibsng_username
    assert refreshed.ibsng_group == "1M-1U-Iran-30G"
    assert refreshed.plan_id == stream_id


@pytest.mark.asyncio
async def test_activate_finished_payment_increments_discount_usage(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.session import async_session_maker as make_session
    from app.services.discounts import create_discount_code, get_discount_code
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import activate_finished_payment, create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/disc2", "np-2002"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with make_session() as session:
        discount = await create_discount_code(
            session, code="ACT10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True,
        )

    async with make_session() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=962, purpose="purchase", plan=plan, vpn_user=None)

    async with make_session() as session, IBSngClient() as client:
        from app.db.models.payment import Payment

        payment = await session.get(Payment, payment.id)
        await activate_finished_payment(session, client, payment)
        await session.commit()

    async with make_session() as session:
        refreshed_discount = await get_discount_code(session, discount.id)
    assert refreshed_discount.used_count == 1
