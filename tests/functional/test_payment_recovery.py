"""Regression tests for the 2026-09-22 production incident.

Payment 16 was paid in full on Plisio (8.785236 TRX, invoice
6ab2a5a944c0a2412901e063, status "completed"). Our callback arrived,
verified and was processed - the audit trail proves it - but IBSng was
unreachable at that moment, so activation failed, the handler answered
500 to ask for a retry, and Plisio stopped retrying. The buyer had paid
and had nothing, and nothing in the system would ever have fixed it.
"""

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

#: The exact field set Plisio sent for the stuck invoice, taken from the
#: production audit trail and Plisio's own record of it.
REAL_CALLBACK: dict[str, Any] = {
    "txn_id": "6ab2a5a944c0a2412901e063",
    "ipn_type": "invoice",
    "merchant": "Homeland",
    "merchant_id": "6ab1457b57bb9b20a4003652",
    "amount": "8.785236",
    "currency": "TRX",
    "order_name": "Homeland: 2 Weeks",
    "confirmations": "20",
    "status": "completed",
    "source_currency": "USD",
    "source_amount": "3.00",
    "source_rate": "0.34545500",
    "invoice_commission": "0.04392618",
    "invoice_sum": "8.78523600",
    "invoice_total_sum": "8.82916218",
}


def _signed_body(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    digest = hmac.new(get_settings().plisio_secret_key.encode(), encoded.encode(), hashlib.sha1).hexdigest()
    return json.dumps({**payload, "verify_hash": digest}, separators=(",", ":"), ensure_ascii=False).encode()


async def _make_client(bot: Any) -> TestClient:
    from app.webhook import create_webhook_app

    client = TestClient(TestServer(create_webhook_app(bot)))
    await client.start_server()
    return client


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


async def _pending_payment(seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch, telegram_id: int,
                           *, plan_id: int | None = None):  # type: ignore[no-untyped-def]
    from app.services.catalog import get_plan
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str):
        return "https://plisio.net/invoice/6ab2a5a944c0a2412901e063", REAL_CALLBACK["txn_id"]

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    # Plan NAMES repeat across categories ("1 Month" exists in Scroll and
    # Stream), so callers that care about a specific plan pass its id.
    if plan_id is None:
        plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        return await create_crypto_payment(
            session, telegram_id=telegram_id, purpose="purchase", plan=plan, vpn_user=None
        )


@pytest.mark.asyncio
async def test_the_real_production_callback_confirms_the_purchase(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact payload from the incident must activate the service."""
    from app.db.models.payment import Payment
    from app.db.models.vpn_user import VPNUser
    from sqlalchemy import select

    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1701)

    client = await _make_client(bot)
    try:
        body = _signed_body({**REAL_CALLBACK, "order_number": str(payment.id)})
        response = await client.post("/webhooks/crypto?json=true", data=body, headers={"Content-Type": "application/json"})
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "paid"
        assert refreshed.resolved_at is not None
        users = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 1701))).scalars().all()
    assert len(users) == 1, "the plan must actually be provisioned"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("order has been placed" in (c[1].get("text") or "").lower() for c in sent)


@pytest.mark.asyncio
async def test_ibsng_outage_leaves_the_payment_recoverable(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The incident itself: a verified callback whose activation cannot
    reach IBSng must ask for a retry and leave the payment open, never
    mark it failed or silently succeed."""
    from app.db.models.payment import Payment
    from app.services.ibsng.exceptions import IBSngError
    from app.services.payments import confirmation

    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1702)

    async def _unreachable(*args: Any, **kwargs: Any) -> str:
        raise IBSngError("IBSng call 'user.getUserInfo' could not reach server: timed out")

    monkeypatch.setattr(confirmation, "activate_finished_payment", _unreachable)

    client = await _make_client(bot)
    try:
        body = _signed_body({**REAL_CALLBACK, "order_number": str(payment.id)})
        response = await client.post("/webhooks/crypto?json=true", data=body, headers={"Content-Type": "application/json"})
        assert response.status == 500, "a 500 is how we ask Plisio to redeliver"
    finally:
        await client.close()

    async with async_session_maker() as session:
        refreshed = await session.get(Payment, payment.id)
    assert refreshed.status == "pending", "the order must stay open, not be failed"


@pytest.mark.asyncio
async def test_reconciler_activates_a_payment_plisio_calls_completed(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery path: once IBSng is back, the sweep finishes an order
    Plisio has marked completed even though no callback ever returned."""
    from app.db.models.payment import Payment
    from app.db.models.vpn_user import VPNUser
    from app.services.payments import reconcile
    from sqlalchemy import select

    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1703)

    async def _completed(txn_id: str) -> str:
        assert txn_id == REAL_CALLBACK["txn_id"]
        return "completed"

    monkeypatch.setattr(reconcile, "get_invoice_status", _completed)

    counts = await reconcile.reconcile_pending_payments(bot)

    assert counts["activated"] == 1
    async with async_session_maker() as session:
        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "paid"
        users = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 1703))).scalars().all()
    assert len(users) == 1
    assert any("order has been placed" in (c[1].get("text") or "").lower()
               for c in fake_session.calls if c[0] == "sendMessage")


@pytest.mark.asyncio
async def test_reconciler_leaves_unpaid_orders_alone(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invoice Plisio has not been paid must never be provisioned."""
    from app.db.models.payment import Payment
    from app.services.payments import reconcile

    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1704)

    async def _still_new(txn_id: str) -> str:
        return "new"

    monkeypatch.setattr(reconcile, "get_invoice_status", _still_new)

    counts = await reconcile.reconcile_pending_payments(bot)

    assert counts["activated"] == 0 and counts["still_open"] == 1
    async with async_session_maker() as session:
        assert (await session.get(Payment, payment.id)).status == "pending"


@pytest.mark.asyncio
async def test_reconciler_never_provisions_twice(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sweeps, or a sweep racing a late callback, must not create a
    second IBSng account for one order."""
    from app.db.models.vpn_user import VPNUser
    from app.services.payments import reconcile
    from sqlalchemy import select

    await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1705)

    async def _completed(txn_id: str) -> str:
        return "completed"

    monkeypatch.setattr(reconcile, "get_invoice_status", _completed)

    first = await reconcile.reconcile_pending_payments(bot)
    second = await reconcile.reconcile_pending_payments(bot)

    assert first["activated"] == 1
    assert second["activated"] == 0, "an already-paid order must not be reprocessed"
    async with async_session_maker() as session:
        users = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 1705))).scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_reconciler_survives_a_plisio_lookup_failure(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One failing lookup must not abort the sweep for other orders."""
    from app.services.payments import reconcile
    from app.services.payments.plisio import PlisioError

    await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1706)

    async def _boom(txn_id: str) -> str:
        raise PlisioError("upstream 500")

    monkeypatch.setattr(reconcile, "get_invoice_status", _boom)

    counts = await reconcile.reconcile_pending_payments(bot)
    assert counts["errors"] == 1 and counts["activated"] == 0


def test_secret_redaction_filter_scrubs_a_leaked_api_key() -> None:
    """httpx logs full request URLs at INFO and Plisio's key travels as a
    query parameter - that is how the live key reached the logs."""
    import logging

    from app.logging_setup import SecretRedactingFilter

    secret = "korC8qVlml_Tc0nLRCc60U-iGzvy7Le8"
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg='HTTP Request: GET https://api.plisio.net/api/v1/invoices/new?api_key=%s "HTTP/1.1 200 OK"' % secret,
        args=None, exc_info=None,
    )

    SecretRedactingFilter([secret]).filter(record)
    assert secret not in record.getMessage()
    assert "***" in record.getMessage()


def test_secret_redaction_filter_ignores_trivial_values() -> None:
    """A blank or very short "secret" would redact half the log."""
    import logging

    from app.logging_setup import SecretRedactingFilter

    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="nothing to hide here", args=None, exc_info=None,
    )
    SecretRedactingFilter(["", "abc"]).filter(record)
    assert record.getMessage() == "nothing to hide here"


def test_secret_redaction_filter_scrubs_non_string_arguments() -> None:
    """httpx logs the request line with an httpx.URL object, not a string,
    and the key rides in its query - the first version of this filter
    missed exactly that and the live key kept reaching the logs."""
    import logging

    from app.logging_setup import SecretRedactingFilter

    class _FakeUrl:
        def __init__(self, text: str) -> None:
            self._text = text

        def __str__(self) -> str:
            return self._text

    secret = "korC8qVlml_Tc0nLRCc60U-iGzvy7Le8"
    url = _FakeUrl(f"https://api.plisio.net/api/v1/invoices/new?api_key={secret}")
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg='HTTP Request: %s %s "%s"', args=("GET", url, "HTTP/1.1 200 OK"), exc_info=None,
    )

    SecretRedactingFilter([secret]).filter(record)
    assert secret not in record.getMessage()
    assert "***" in record.getMessage()


@pytest.mark.asyncio
async def test_reconciler_skips_payments_from_a_previous_provider(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NOWPayments-era rows carry that provider's numeric ids, which
    Plisio 404s forever - they must not be looked up at all."""
    from app.db.models.payment import Payment
    from app.services.payments import reconcile

    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1707)
    async with async_session_maker() as session:
        stale = await session.get(Payment, payment.id)
        stale.provider = "nowpayments"
        stale.provider_payment_id = "4617681042"
        await session.commit()

    async def _must_not_be_called(txn_id: str) -> str:
        raise AssertionError(f"a {'nowpayments'} order must never be looked up on Plisio (got {txn_id})")

    monkeypatch.setattr(reconcile, "get_invoice_status", _must_not_be_called)

    counts = await reconcile.reconcile_pending_payments(bot)
    assert counts["checked"] == 0 and counts["errors"] == 0


async def _deliver(bot: Any, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch, telegram_id: int,
                   *, lang: str | None = None, plan_id: int | None = None):  # type: ignore[no-untyped-def]
    """Drive one purchase through the real callback and hand back the
    delivery message that reached the buyer."""
    from app.services.bot_users import record_seen, set_language

    if lang is not None:
        async with async_session_maker() as session:
            await record_seen(session, telegram_id, None)
            await set_language(session, telegram_id, lang)

    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=telegram_id, plan_id=plan_id)
    client = await _make_client(bot)
    try:
        body = _signed_body({**REAL_CALLBACK, "order_number": str(payment.id)})
        await client.post("/webhooks/crypto?json=true", data=body, headers={"Content-Type": "application/json"})
    finally:
        await client.close()
    return payment


@pytest.mark.asyncio
async def test_delivery_message_carries_the_order_details_in_english(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    payment = await _deliver(bot, seeded_catalog, monkeypatch, 1801)

    sent = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == 1801]
    text = sent[-1][1]["text"]
    assert "Your order has been placed successfully" in text
    assert "1 Month" in text
    assert "30 days from first connection" in text
    assert "10 GB" in text
    # Separate spans: tap-to-copy works per span, so one combined block
    # would force the buyer to hand-edit the credentials apart.
    assert f"<code>{payment.ibsng_username}</code>" in text
    assert f"<code>{payment.ibsng_password}</code>" in text

    buttons = {b["text"]: b["callback_data"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert buttons["📘 Tutorial"] == "menu:tutorials"
    assert buttons["🔙 Back to Main Menu"] == "menu:root"


@pytest.mark.asyncio
async def test_delivery_message_is_persian_for_a_persian_buyer(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    payment = await _deliver(bot, seeded_catalog, monkeypatch, 1802, lang="fa")

    sent = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == 1802]
    text = sent[-1][1]["text"]
    assert "سفارش شما با موفقیت ثبت شد" in text
    assert "روز از زمان اولین اتصال" in text
    assert f"<code>{payment.ibsng_username}</code>" in text
    buttons = {b["text"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert "📘 آموزش" in buttons and "🔙 بازگشت به منوی اصلی" in buttons


@pytest.mark.asyncio
async def test_unlimited_plan_renders_volume_as_unlimited(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan with data_cap_mb=0 must read "Unlimited", never "0 MB"."""
    unlimited = next(
        (p for p in seeded_catalog["plans"] if p["data_cap_mb"] == 0 and p["category"] != "trial"), None
    )
    if unlimited is None:
        pytest.skip("no unlimited plan in the seeded catalog")

    await _deliver(bot, seeded_catalog, monkeypatch, 1803, plan_id=unlimited["id"])

    sent = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == 1803]
    assert "Unlimited" in sent[-1][1]["text"]


@pytest.mark.asyncio
async def test_missing_password_still_delivers_the_order(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service IS provisioned - an unreadable password must degrade
    to the contact-support variant, never look like a failed order."""
    from app.services.payments import confirmation

    async def _no_password(payment: Any, username: str) -> None:
        return None

    monkeypatch.setattr(confirmation, "_recover_password", _no_password)
    payment = await _deliver(bot, seeded_catalog, monkeypatch, 1804)

    sent = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == 1804]
    text = sent[-1][1]["text"]
    assert "contact support" in text.lower()
    assert payment.ibsng_username in text
    assert "Your order has been placed successfully" in text


@pytest.mark.asyncio
async def test_renewal_reads_the_password_back_from_ibsng(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A renewal payment carries no password - the account keeps its own -
    so it is read back the way the trial flow does."""
    from app.db.models.payment import Payment
    from app.services.payments import confirmation

    payment = await _pending_payment(seeded_catalog, monkeypatch, telegram_id=1805)
    async with async_session_maker() as session:
        row = await session.get(Payment, payment.id)
        row.ibsng_password = None
        await session.commit()

    async def _from_ibsng(payment_row: Any, username: str) -> str:
        return "readback99"

    monkeypatch.setattr(confirmation, "_recover_password", _from_ibsng)

    client = await _make_client(bot)
    try:
        body = _signed_body({**REAL_CALLBACK, "order_number": str(payment.id)})
        await client.post("/webhooks/crypto?json=true", data=body, headers={"Content-Type": "application/json"})
    finally:
        await client.close()

    sent = [c for c in fake_session.calls if c[0] == "sendMessage" and c[1]["chat_id"] == 1805]
    assert "<code>readback99</code>" in sent[-1][1]["text"]
