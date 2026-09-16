from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import get_settings
from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


def _sign(payload: dict[str, Any], secret: str | None = None) -> tuple[bytes, str]:
    secret = secret if secret is not None else get_settings().nowpayments_ipn_secret
    raw_body = json.dumps(payload).encode()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()
    return raw_body, signature


async def _make_client(bot: Any) -> TestClient:
    from app.webhook import create_webhook_app

    app = create_webhook_app(bot)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, _ = _sign({"order_id": "1", "payment_status": "finished"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": "wrong"})
        assert response.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_ignores_unknown_order_id(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({"order_id": "999999", "payment_status": "finished", "payment_id": "np-x"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_ignores_out_of_int32_range_order_id(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({"order_id": "99999999999", "payment_status": "finished", "payment_id": "np-x"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_finished_activates_purchase_and_notifies_user(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh1", "np-wh-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=970, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-1", "payment_status": "finished",
            "actually_paid": "5.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from app.db.models.payment import Payment
        from app.db.models.vpn_user import VPNUser
        from sqlalchemy import select

        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "paid"
        assert refreshed.vpn_user_id is not None

        vpn_user = await session.get(VPNUser, refreshed.vpn_user_id)
        assert vpn_user.telegram_id == 970

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "confirmed" in sent[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_webhook_duplicate_finished_delivery_is_idempotent(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh2", "np-wh-2"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=971, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-2", "payment_status": "finished",
            "actually_paid": "5.0",
        })
        for _ in range(2):
            response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
            assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.vpn_user import VPNUser

        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 971))).scalars().all()
    assert len(rows) == 1  # NOT two - the second IPN delivery was a no-op

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1  # only the first delivery notified the user


@pytest.mark.asyncio
async def test_webhook_partially_paid_does_not_activate_and_shows_no_dollar_figure(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh3", "np-wh-3"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=972, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-3", "payment_status": "partially_paid",
            "actually_paid": "3.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.payment import Payment
        from app.db.models.vpn_user import VPNUser

        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "partially_paid"
        assert refreshed.paid_amount == Decimal("3.0")

        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 972))).scalars().all()
    assert rows == []  # never activated

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    text = sent[0][1]["text"]
    assert "$" not in text  # never fabricates a dollar shortfall from crypto units
    buttons = [b["text"] for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "💰 Finish Payment" in buttons


@pytest.mark.asyncio
async def test_webhook_failed_marks_payment_failed(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh4", "np-wh-4"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=973, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-4", "payment_status": "expired",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from app.db.models.payment import Payment

        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "failed"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "did not complete" in sent[0][1]["text"].lower()
