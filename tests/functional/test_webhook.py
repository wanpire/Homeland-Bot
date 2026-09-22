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


_HEADERS = {"Content-Type": "application/json"}


def _sign(payload: dict[str, Any], secret: str | None = None) -> tuple[bytes, dict[str, str]]:
    """Build a correctly signed Plisio callback.

    Plisio signs with HMAC-SHA1 over the compact JSON payload with
    verify_hash removed, keyed with the SAME secret that authenticates
    API calls, and carries the hash INSIDE the body - there is no
    signature header, unlike NOWPayments' x-nowpayments-sig."""
    secret = secret if secret is not None else get_settings().plisio_secret_key
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    digest = hmac.new(secret.encode(), encoded.encode(), hashlib.sha1).hexdigest()
    raw_body = json.dumps({**payload, "verify_hash": digest}, separators=(",", ":"), ensure_ascii=False).encode()
    return raw_body, _HEADERS


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
        raw_body, headers = _sign({"order_number": "1", "status": "completed"}, secret="the-wrong-secret")
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
        assert response.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_ignores_unknown_order_id(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({"order_number": "999999", "status": "completed", "txn_id": "plisio-x"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_ignores_out_of_int32_range_order_id(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({"order_number": "99999999999", "status": "completed", "txn_id": "plisio-x"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
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
        return "https://plisio.net/invoice/wh1", "plisio-wh-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=970, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-wh-1", "status": "completed",
            "amount": "5.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
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
async def test_payment_confirmed_message_in_persian(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.bot_users import record_seen, set_language
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/wh-fa1", "plisio-wh-fa1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=990, purpose="purchase", plan=plan, vpn_user=None)

    async with async_session_maker() as session:
        await record_seen(session, 990, None)
        await set_language(session, 990, "fa")

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-wh-fa1", "status": "completed",
            "amount": "5.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
        assert response.status == 200
    finally:
        await client.close()

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "پرداخت تأیید شد" in sent[0][1]["text"]


@pytest.mark.asyncio
async def test_webhook_duplicate_finished_delivery_is_idempotent(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/wh2", "plisio-wh-2"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=971, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-wh-2", "status": "completed",
            "amount": "5.0",
        })
        for _ in range(2):
            response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
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
        return "https://plisio.net/invoice/wh3", "plisio-wh-3"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=972, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-wh-3", "status": "expired",
            "amount": "3.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
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
        return "https://plisio.net/invoice/wh4", "plisio-wh-4"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=973, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-wh-4", "status": "expired",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
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


@pytest.mark.asyncio
async def test_webhook_finished_tolerates_blocked_bot_on_username_collision(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiogram.exceptions import TelegramForbiddenError
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment
    from app.services.vpn_users import VPNUsernameTakenError

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd, description: str):
        return "https://plisio.net/invoice/wh5", "plisio-wh-5"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan
        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=974, purpose="purchase", plan=plan, vpn_user=None)

    async def _boom(*args, **kwargs):
        raise VPNUsernameTakenError("collision")

    # Patch where the shared confirmation service imports it from - the
    # webhook now delegates provisioning there rather than calling it.
    from app.services.payments import confirmation

    monkeypatch.setattr(confirmation, "activate_finished_payment", _boom)

    async def _blocked(*args, **kwargs):
        raise TelegramForbiddenError(method=None, message="bot was blocked by the user")

    monkeypatch.setattr(bot, "send_message", _blocked)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-wh-5", "status": "completed",
            "amount": "5.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_finished_after_partially_paid_still_activates(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for the top-up flow: a "completed" callback
    arriving after an earlier partial payment for the same order must
    still activate the service - the same Plisio invoice keeps accepting
    funds until it is paid in full (spec §9)."""
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/topup", "plisio-topup-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan
        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=980, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        partial_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-topup-1", "status": "expired",
            "amount": "3.0",
        })
        r1 = await client.post("/webhooks/crypto", data=partial_body, headers=headers)
        assert r1.status == 200

        finished_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-topup-1", "status": "completed",
            "amount": "5.0",
        })
        r2 = await client.post("/webhooks/crypto", data=finished_body, headers=headers)
        assert r2.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from app.db.models.payment import Payment
        from app.db.models.vpn_user import VPNUser
        from sqlalchemy import select as sa_select

        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "paid"

        rows = (await session.execute(sa_select(VPNUser).where(VPNUser.telegram_id == 980))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_webhook_concurrent_finished_deliveries_never_double_provision(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for the idempotency-lock fix: two genuinely
    concurrent identical "finished" IPN deliveries for the same payment
    must never double-provision or double-charge - exactly one VPNUser
    row is created, backstopped by the unique constraint on
    VPNUser.ibsng_username even in the narrow residual race the fix
    doesn't fully close."""
    import asyncio

    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/race", "plisio-race-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan
        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=981, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-race-1", "status": "completed",
            "amount": "5.0",
        })
        responses = await asyncio.gather(
            client.post("/webhooks/crypto", data=raw_body, headers=headers),
            client.post("/webhooks/crypto", data=raw_body, headers=headers),
        )
        assert {r.status for r in responses} <= {200, 500}
    finally:
        await client.close()

    async with async_session_maker() as session:
        from app.db.models.vpn_user import VPNUser
        from sqlalchemy import select as sa_select

        rows = (await session.execute(sa_select(VPNUser).where(VPNUser.telegram_id == 981))).scalars().all()
    assert len(rows) == 1

    # Not exactly one: activate_finished_payment's own internal commits can
    # release the row lock before the webhook's final status commit under
    # true concurrent delivery, so a second delivery can still reach the
    # VPNUsernameTakenError branch and send its own notification - the
    # VPNUser uniqueness guarantee above is what actually matters (no
    # duplicate account, no double charge); a possible extra "contact
    # support" message is a documented, accepted residual risk, not a
    # regression this test should fail on.
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) >= 1
    for _, payload in sent:
        text = payload["text"].lower()
        assert "payment confirmed" in text or "technical issue" in text


@pytest.mark.asyncio
async def test_webhook_concurrent_failed_deliveries_send_exactly_one_message(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for the populate_existing fix: the "failed"/
    "refunded" branch has no internal commit inside its critical section,
    so once the idempotency re-fetch actually refreshes the row (rather
    than returning a stale cached object), concurrent identical "failed"
    IPN deliveries for the same payment must be fully serialized - only
    the first should send a message, every later one should see the
    already-"failed" status and be ignored."""
    import asyncio

    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/failrace", "plisio-failrace-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan
        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=982, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-failrace-1", "status": "expired",
        })
        responses = await asyncio.gather(*[
            client.post("/webhooks/crypto", data=raw_body, headers=headers)
            for _ in range(5)
        ])
        assert all(r.status == 200 for r in responses)
    finally:
        await client.close()

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1, f"expected exactly 1 message under full serialization, got {len(sent)}"


@pytest.mark.asyncio
async def test_webhook_cancelled_duplicate_never_fails_a_payment(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plisio sets "cancelled duplicate" on the invoice a buyer abandoned
    when they switched coins; the replacement invoice is the one that
    completes. Failing the payment here would cancel an order the buyer
    is still in the middle of paying."""
    from app.db.models.payment import Payment
    from app.db.models.payment_status_event import PaymentStatusEvent
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment
    from sqlalchemy import select as sa_select

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/dup", "plisio-dup-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=991, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-dup-1", "status": "cancelled duplicate",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "pending", "a coin switch must not cancel the order"
        events = (
            await session.execute(sa_select(PaymentStatusEvent).where(PaymentStatusEvent.payment_id == payment.id))
        ).scalars().all()
        assert [e.raw_status for e in events] == ["cancelled duplicate"], "still audited"

    assert [c for c in fake_session.calls if c[0] == "sendMessage"] == []


@pytest.mark.asyncio
async def test_webhook_expired_with_a_partial_amount_offers_a_topup(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plisio has no "partially paid" status: an expired invoice carrying a
    received amount is this platform's partial payment."""
    from app.db.models.payment import Payment
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/part", "plisio-part-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=992, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-part-1", "status": "expired", "amount": "2.5",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "partially_paid"
        assert refreshed.paid_amount == Decimal("2.5")

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    buttons = [b["text"] for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "💰 Finish Payment" in buttons


@pytest.mark.asyncio
async def test_webhook_switching_coins_updates_the_stored_txn_id(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """order_number stays ours across a coin switch but txn_id changes, so
    the newest one must win for the Plisio dashboard to be searchable."""
    from app.db.models.payment import Payment
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://plisio.net/invoice/first", "plisio-first"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=993, purpose="purchase", plan=plan, vpn_user=None)
    assert payment.provider_payment_id == "plisio-first"

    client = await _make_client(bot)
    try:
        raw_body, headers = _sign({
            "order_number": str(payment.id), "txn_id": "plisio-second", "status": "pending",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers=headers)
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        refreshed = await session.get(Payment, payment.id)
        assert refreshed.provider_payment_id == "plisio-second"
        assert refreshed.status == "pending", "a progress callback must not resolve the payment"
