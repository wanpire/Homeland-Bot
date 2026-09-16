# Crypto Payment (NOWPayments) — Design Spec

Date: 2026-09-16
Status: proposed
Parent spec: `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` §6
(Payment abstraction) — this spec is the first concrete implementation of
that design, and deviates from it in one place (§4 below), with rationale.

## 1. Summary

Replaces Buy Subscription's and Renew Service's "🚧 payment methods coming
soon" walls with a real crypto payment path via NOWPayments' **hosted
Invoice API** (not the raw Payment API, not manual tx-hash collection).
The user taps "₿ Pay with Crypto", the bot creates a NOWPayments invoice
and hands them a link to NOWPayments' own hosted payment page (coin
selection, address, QR code — all handled by NOWPayments, never
recreated inside the bot). NOWPayments calls back via a signed IPN
webhook; only a `finished` (fully paid and settled) status provisions
the VPN account and confirms the order — every other status is tracked
but does not activate anything.

**No Stripe integration exists in this codebase yet** (verified: no
`app/services/payments/`, no `app/webhook.py`, no `Payment` model —
confirmed via `grep -rn "class PaymentProvider" app/` returning nothing,
per the `payment-provider-abstraction` skill's own freshness check). This
spec builds the payment foundation from scratch, scoped to crypto only.
Stripe stays deferred until its own credentials arrive; the
`PaymentProvider` abstraction from spec §6 is built now specifically so
Stripe can slot in later without restructuring this code.

**Reference implementation:** the sibling project AloBot
(`/Users/peyman/telegram-bot`) has a working, production NOWPayments
integration at `app/services/nowpayments.py` and `app/webhook.py`. Spec
§6 explicitly names it as the closest confirmed reference for this exact
"hosted invoice + signed IPN" shape, and this spec follows its proven
patterns closely: the invoice-creation POST shape, the HMAC-SHA512
canonical-JSON signature verification technique, and running the webhook
server in the same process as the bot's polling loop via
`aiohttp.web.AppRunner`/`TCPSite` started before `dp.start_polling(bot)`.
It is **not** a drop-in — AloBot's `Payment` model carries fields for a
manual admin-approval branch and an invoice-numbering scheme that
Homeland's spec explicitly does not want (§6: "Homeland has no manual
admin-approval branch"), so this spec's `Payment` model is trimmed to
what Homeland actually needs.

## 2. Navigation / architecture overview

No new callback-data namespace beyond what Buy and Renew already have.
The `✅ Buy` / `✅ Renew` buttons on the existing price-summary screens
(`buy:confirm:<plan_id>`, `renew:confirm:<vpn_user_id>:<plan_id>`) are
relabeled `₿ Pay with Crypto` and their handlers stop showing the
coming-soon wall — they create a `Payment` row + NOWPayments invoice and
edit the message to a link screen instead. **No new payment-method
picker screen is added** — with exactly one method available, a picker
screen would be a single-button dead end; that screen gets built when
Stripe actually lands, not preemptively (YAGNI). The rest of both flows
(category picker, tier picker, price summary) is completely unchanged.

New pieces:
- `app/db/models/payment.py`, `app/db/models/payment_status_event.py` +
  migration `0007_payments.py`
- `app/services/payments/` — `base.py`, `nowpayments.py`,
  `crypto_provider.py`, `service.py`
- `app/webhook.py` — the aiohttp IPN receiver
- `app/main.py` — starts the webhook server alongside polling
- `app/config.py` — renamed/added settings
- `app/bot/handlers/buy.py`, `app/bot/handlers/renew.py` — confirm
  handlers rewritten
- `app/bot/keyboards/buy.py`, `app/bot/keyboards/renew.py` — one button
  label + one new keyboard function each
- `docker-compose.yml` — expose `webhook_port`

## 3. Data model

### `Payment` (`app/db/models/payment.py`)

```python
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Payment(Base):
    """One crypto payment attempt for one plan, tied either to a new
    purchase (purpose="purchase", vpn_user_id starts NULL, set once
    create_vpn_user succeeds) or a renewal of an existing owned service
    (purpose="renew", vpn_user_id set at creation time and never
    changes). group_name/data_cap_mb are snapshotted from the Plan at
    creation time - not re-derived from plan_id later - so an admin
    editing the catalog mid-payment can never retroactively change what
    a pending payment provisions, mirroring VPNUser.data_cap_mb's own
    snapshot rationale (see that model's docstring).

    status is Homeland's own coarse view (pending/paid/partially_paid/
    failed/refunded), separate from the raw NOWPayments payment_status
    strings recorded per-IPN in PaymentStatusEvent - never conflate the
    two: NOWPayments has finer states (waiting/confirming/sending) that
    don't need their own Payment.status value, since nothing user-facing
    or provisioning-related happens until "finished"."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # "purchase" | "renew"
    vpn_user_id: Mapped[int | None] = mapped_column(ForeignKey("vpn_users.id"), nullable=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    discount_code_id: Mapped[int | None] = mapped_column(
        ForeignKey("discount_codes.id", ondelete="SET NULL"), nullable=True
    )

    group_name: Mapped[str] = mapped_column(String(64))
    data_cap_mb: Mapped[int] = mapped_column(Integer)

    # Only set for purpose="purchase" - a renew targets an existing,
    # already-credentialed account (vpn_user_id above), so these stay
    # NULL for purpose="renew".
    ibsng_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ibsng_password: Mapped[str | None] = mapped_column(String(128), nullable=True)

    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # NOWPayments' IPN "actually_paid" field, in the invoice's pay_currency
    # (e.g. USDT) - NOT necessarily USD, despite amount_usd/original_amount_usd
    # above being USD. Never presented to a user as a dollar figure (see §9's
    # partially_paid handling) - stored for audit/support cross-reference
    # against the NOWPayments dashboard only.
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    provider: Mapped[str] = mapped_column(String(16), default="nowpayments")
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # pending -> paid | partially_paid | failed | refunded
    status: Mapped[str] = mapped_column(String(16), default="pending")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`data_cap_mb` matches `VPNUser.data_cap_mb`'s type exactly (a plain
snapshot integer, not a foreign key) — same rationale, see that model's
docstring.

### `PaymentStatusEvent` (`app/db/models/payment_status_event.py`)

```python
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentStatusEvent(Base):
    """One row per IPN delivery received for a Payment - an append-only
    audit trail of every raw NOWPayments payment_status this project has
    ever seen for that payment, independent of Payment.status (which
    only tracks Homeland's own coarse view). Never updated or deleted."""

    __tablename__ = "payment_status_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    raw_status: Mapped[str] = mapped_column(String(32))
    # Same caveat as Payment.paid_amount - NOWPayments' pay_currency units,
    # not USD.
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### Migration `0007_payments.py`

Two `op.create_table` calls (payments, then payment_status_events, since
the second has an FK to the first), following `0006_discount_codes.py`'s
exact style: explicit `nullable=`/`server_default=` on every column, one
`op.create_index` for the unique `provider_payment_id` index, a
`downgrade()` that drops both tables and the index in reverse order.

## 4. Deviation from spec §6: `on_payment_confirmed` is not a `PaymentProvider` method

Spec §6 sketched `PaymentProvider.on_payment_confirmed(event)` as
"creates/renews the VPN user and marks the Payment approved." Building
this for real surfaces a problem: that logic needs `VPNUser`,
`IBSngClient`, `create_vpn_user`, and `renew_and_change_group` — none of
which a *payment provider* should need to know about. A provider's job
is talking to its gateway (create an invoice, verify a signature); the
purchase-vs-renew branching and IBSng provisioning is Homeland
domain logic that has nothing to do with which gateway was used, and
will be identical the day Stripe's webhook route also needs to call it.
AloBot's own actual (working, not sketched) `webhook.py` confirms this
split is right: the purchase/renew branching lives in the webhook
route/service layer there too, not inside `nowpayments.py`.

**This spec keeps `PaymentProvider` to two methods** —
`create_invoice`/`verify_webhook` — and puts activation logic in
`app/services/payments/service.py`'s `activate_finished_payment`
(§6 below), called directly by the webhook route once it has a verified,
`finished`-status event. `on_payment_confirmed` is dropped from the ABC.
This is a deliberate, reasoned correction to the parent spec, not an
oversight — flagging it explicitly here rather than silently diverging.

## 5. Config (`app/config.py`)

Renames the three existing, never-yet-referenced placeholder fields to
NOWPayments-specific names (matching the exact env var names requested:
pydantic-settings uppercases the field name, so `nowpayments_api_key`
reads `NOWPAYMENTS_API_KEY`):

```python
    # NOWPayments - config placeholders only, no live keys yet.
    # create_crypto_payment raises PaymentProviderNotConfiguredError while
    # nowpayments_api_key is blank, so the bot can run today with crypto
    # payment visibly unavailable until real keys are provisioned.
    #
    # Settlement/outcome currency (USDT on TRC-20, primary) is configured
    # in the NOWPayments dashboard itself (payout wallet address) - not
    # in code, and not something this app ever needs to know about.
    nowpayments_api_key: str = ""
    nowpayments_ipn_secret: str = ""
    nowpayments_ipn_callback_url: str = ""

    # Used only to build NOWPayments' optional success_url/cancel_url
    # (a deep link back into the bot after the hosted payment page) -
    # blank means those params are simply omitted from the invoice
    # request; NOWPayments shows its own default confirmation page
    # instead. Real confirmation always happens via the IPN-triggered
    # Telegram message regardless, so this is cosmetic only.
    bot_username: str = ""
```

This removes `crypto_gateway_api_key`, `crypto_gateway_ipn_secret`,
`crypto_gateway_ipn_callback_url` (grep confirms zero references to any
of the three anywhere outside `config.py` itself, so removing them is
safe). `webhook_port: int = 8090` already exists and is reused as-is.
`stripe_api_key`/`stripe_webhook_secret` are untouched — still unused
placeholders, Stripe is not part of this spec.

## 6. NOWPayments client (`app/services/payments/nowpayments.py`)

A near-direct port of AloBot's `app/services/nowpayments.py`, adjusted
for Homeland's settings names and adding `success_url`/`cancel_url`
(requested explicitly, absent from AloBot's version):

```python
"""Client for NOWPayments' hosted Invoice API. We use the Invoice flow
(not the raw Payment API) so NOWPayments handles coin selection, address
generation, and the QR/payment page entirely - we only need an
invoice_url to hand the buyer and an IPN webhook to hear back. Ported
from the sibling project's app/services/nowpayments.py - see
docs/superpowers/specs/2026-09-16-crypto-payment-design.md.

Reference: https://documenter.getpostman.com/view/7907941/S1a32n38
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import httpx

from app.config import get_settings

_BASE_URL = "https://api.nowpayments.io/v1"


class NowPaymentsError(Exception):
    """Raised when the NOWPayments API returns an error."""


class PaymentProviderNotConfiguredError(Exception):
    """Raised instead of a confusing raw API failure when nowpayments_api_key
    is blank - lets the bot run with crypto payment visibly unavailable
    until real keys are provisioned (spec §5)."""


async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
    """Returns (invoice_url, payment_id) - payment_id is NOWPayments'
    own id for this invoice, stored on Payment.provider_payment_id for
    IPN lookup."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    payload: dict[str, str] = {
        "price_amount": str(amount),
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": description,
    }
    if settings.nowpayments_ipn_callback_url:
        payload["ipn_callback_url"] = settings.nowpayments_ipn_callback_url
    if settings.bot_username:
        payload["success_url"] = f"https://t.me/{settings.bot_username}"
        payload["cancel_url"] = f"https://t.me/{settings.bot_username}"

    headers = {"x-api-key": settings.nowpayments_api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{_BASE_URL}/invoice", json=payload, headers=headers)

    if response.status_code >= 400:
        raise NowPaymentsError(f"NOWPayments invoice creation failed: {response.status_code} {response.text}")

    data = response.json()
    invoice_url = data.get("invoice_url")
    payment_id = data.get("id")
    if not invoice_url or not payment_id:
        raise NowPaymentsError(f"NOWPayments response missing invoice_url/id: {data!r}")
    return invoice_url, str(payment_id)


def verify_ipn_signature(raw_body: bytes, signature: str, ipn_secret: str) -> bool:
    """NOWPayments signs a sorted-keys JSON encoding of the IPN payload
    with HMAC-SHA512 using the IPN secret (separate from the API key) -
    exact technique ported from AloBot's nowpayments.py, called out in
    the payment-provider-abstraction skill as easy to get subtly wrong."""
    if not signature:
        return False
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return False
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(ipn_secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
```

Note: NOWPayments' actual invoice-creation response includes an `id`
field (the payment/invoice id) alongside `invoice_url` — AloBot's own
client discards it (they look it up differently), but this spec's IPN
handler needs it up front to store as `Payment.provider_payment_id` at
creation time, not just parse it later. If real API testing during
implementation shows a different response field name, that's an
implementation-time correction, not a design one.

## 7. `PaymentProvider` abstraction (`app/services/payments/base.py`, `crypto_provider.py`)

```python
# app/services/payments/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class WebhookEvent:
    provider_payment_id: str
    order_id: str
    raw_status: str
    paid_amount: Decimal | None  # in the invoice's pay_currency, not USD - see Payment.paid_amount


class PaymentProvider(ABC):
    @abstractmethod
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        """Returns (url to hand the buyer, provider's own payment id)."""

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        """Verifies signature, parses the callback. None if invalid."""
```

```python
# app/services/payments/crypto_provider.py
from __future__ import annotations

import json
from decimal import Decimal

from app.config import get_settings
from app.services.payments import nowpayments
from app.services.payments.base import PaymentProvider, WebhookEvent


class CryptoProvider(PaymentProvider):
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return await nowpayments.create_invoice(order_id=order_id, amount=amount_usd, description=description)

    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        settings = get_settings()
        if not nowpayments.verify_ipn_signature(raw_body, signature, settings.nowpayments_ipn_secret):
            return None
        data = json.loads(raw_body)
        order_id = data.get("order_id")
        payment_id = data.get("payment_id") or data.get("id")
        if not order_id or not payment_id:
            return None
        paid = data.get("actually_paid")
        return WebhookEvent(
            provider_payment_id=str(payment_id),
            order_id=str(order_id),
            raw_status=data.get("payment_status", ""),
            paid_amount=Decimal(str(paid)) if paid is not None else None,
        )
```

## 8. Payments service (`app/services/payments/service.py`)

The Homeland-domain orchestration layer both the bot handlers and the
webhook route call into:

```python
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discount_code import DiscountCode
from app.db.models.payment import Payment
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.services.discounts import discount_price, find_best_auto_discount, increment_discount_usage
from app.services.ibsng.client import IBSngClient
from app.services.payments.base import PaymentProvider
from app.services.payments.crypto_provider import CryptoProvider
from app.services.vpn_users import create_vpn_user, generate_vpn_credentials, renew_and_change_group

_provider: PaymentProvider = CryptoProvider()


async def create_crypto_payment(
    session: AsyncSession,
    *,
    telegram_id: int,
    purpose: str,  # "purchase" | "renew"
    plan: Plan,
    vpn_user: VPNUser | None,  # required for purpose="renew", None for "purchase"
) -> Payment:
    discount: DiscountCode | None = await find_best_auto_discount(session, plan.id)
    amount = discount_price(plan.price_usd, discount.percent) if discount is not None else plan.price_usd

    payment = Payment(
        telegram_id=telegram_id,
        purpose=purpose,
        vpn_user_id=vpn_user.id if vpn_user is not None else None,
        plan_id=plan.id,
        discount_code_id=discount.id if discount is not None else None,
        group_name=plan.group_name,
        data_cap_mb=plan.data_cap_mb,
        amount_usd=amount,
        original_amount_usd=plan.price_usd if discount is not None else None,
    )
    if purpose == "purchase":
        payment.ibsng_username, payment.ibsng_password = generate_vpn_credentials()

    # Committed BEFORE calling the provider, deliberately - NOWPayments'
    # order_id must be a real, permanent local id, which only exists
    # once this row is committed (not merely flushed - a flush's id
    # survives a later rollback only until the transaction actually
    # ends, and this session's transaction doesn't end until the second
    # commit below). If create_invoice then fails, this row is left
    # behind as an orphaned "pending, no invoice_url" Payment - accepted
    # as a harmless stale row, same as any other abandoned checkout
    # (spec §12) - rather than risk order_id pointing at a row that
    # later vanished.
    session.add(payment)
    await session.commit()
    await session.refresh(payment)

    invoice_url, provider_payment_id = await _provider.create_invoice(
        order_id=str(payment.id), amount_usd=amount, description=f"Homeland: {plan.name}"
    )
    payment.invoice_url = invoice_url
    payment.provider_payment_id = provider_payment_id
    await session.commit()
    await session.refresh(payment)
    return payment


async def activate_finished_payment(session: AsyncSession, client: IBSngClient, payment: Payment) -> str:
    """Only called once, guarded by the webhook route's idempotency check
    (payment.status == "pending") before this runs. Returns the
    username to show the buyer - either newly created or the existing
    renewed one."""
    plan = await session.get(Plan, payment.plan_id)
    if payment.purpose == "purchase":
        vpn_user = await create_vpn_user(
            session, client,
            telegram_id=payment.telegram_id,
            username=payment.ibsng_username,
            password=payment.ibsng_password,
            group_name=payment.group_name,
            data_cap_mb=payment.data_cap_mb,
            plan_id=payment.plan_id,
        )
        payment.vpn_user_id = vpn_user.id
        username = vpn_user.ibsng_username
    else:
        vpn_user = await session.get(VPNUser, payment.vpn_user_id)
        await renew_and_change_group(
            session, client,
            username=vpn_user.ibsng_username,
            new_group_name=payment.group_name,
            new_plan_id=payment.plan_id,
            new_data_cap_mb=payment.data_cap_mb,
        )
        username = vpn_user.ibsng_username

    if payment.discount_code_id is not None:
        await increment_discount_usage(session, payment.discount_code_id)

    return username
```

`increment_discount_usage(session, discount_code_id)` is a new one-line
function in `app/services/discounts.py` (`used_count += 1`, commit) —
`discount_code.py`'s own docstring already notes `used_count` "stays at
its default of 0 until the Buy/payments plan wires up the increment
call," which is exactly this spec.

**Purchase failure modes not swallowed silently:** if `create_vpn_user`
raises `VPNUsernameTakenError` (the pre-generated username collided —
astronomically unlikely given `generate_vpn_credentials`' randomness,
but the function can raise it), the webhook route (§9) catches it,
leaves `payment.status="pending"` unchanged (so a retried IPN delivery
can try again — NOWPayments does retry), logs an error, and sends the
user a "payment received, contact support" message rather than crashing
the whole IPN request. Mirrors AloBot's `_handle_nowpayments_ipn`
exactly for this case.

## 9. Webhook server (`app/webhook.py`)

```python
from __future__ import annotations

import datetime as dt
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

from app.db.models.payment import Payment
from app.db.models.payment_status_event import PaymentStatusEvent
from app.db.session import async_session_maker
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.payments.crypto_provider import CryptoProvider
from app.services.payments.service import activate_finished_payment
from app.services.vpn_users import VPNUsernameTakenError

logger = logging.getLogger(__name__)

_provider = CryptoProvider()

_FINAL_STATUSES = {
    "finished": "paid",
    "partially_paid": "partially_paid",
    "failed": "failed",
    "expired": "failed",
    "refunded": "refunded",
}
# waiting / confirming / confirmed / sending are progress states - logged
# via PaymentStatusEvent but never change Payment.status or notify the user.


def create_webhook_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/webhooks/crypto", _handle_crypto_ipn)
    return app


async def _handle_crypto_ipn(request: web.Request) -> web.Response:
    raw_body = await request.read()
    signature = request.headers.get("x-nowpayments-sig", "")

    event = _provider.verify_webhook(raw_body, signature)
    if event is None:
        logger.warning("Crypto IPN signature/payload invalid")
        return web.Response(status=401, text="invalid signature")

    bot: Bot = request.app["bot"]

    # int32-range guard: Payment.id is a PostgreSQL `integer` column, and
    # a numerically valid but out-of-range order_id would otherwise pass
    # .isdigit() only to crash session.get() with an unhandled
    # asyncpg.DataError - the exact class of bug the Renew Service
    # feature's final review found and fixed for callback_data ids;
    # applying the same lesson here since order_id is just as attacker-
    # reachable (NOWPayments echoes back whatever order_id was sent, but
    # nothing stops a malicious actor from POSTing directly to this
    # public endpoint with a crafted body).
    order_id_value: int | None = None
    if event.order_id.isdigit() and 0 < int(event.order_id) <= 2**31 - 1:
        order_id_value = int(event.order_id)

    async with async_session_maker() as session:
        payment = await session.get(Payment, order_id_value) if order_id_value is not None else None
        if payment is None:
            return web.Response(status=200, text="ignored")

        session.add(PaymentStatusEvent(
            payment_id=payment.id, raw_status=event.raw_status, paid_amount=event.paid_amount,
        ))
        await session.commit()

        if event.raw_status not in _FINAL_STATUSES:
            return web.Response(status=200, text="ok")  # progress state, nothing to do

        # Idempotency guard: a Payment only leaves "pending" once, right
        # here. A replayed/duplicate IPN for an already-resolved payment
        # is a no-op - this is the ONLY gate needed, since
        # provider_payment_id already uniquely identifies the payment
        # via order_id -> payment.id, and this check covers every
        # duplicate-delivery scenario NOWPayments' own retry behavior
        # can produce.
        if payment.status != "pending":
            return web.Response(status=200, text="ignored")

        new_status = _FINAL_STATUSES[event.raw_status]

        if new_status == "paid":
            async with IBSngClient() as client:
                try:
                    username = await activate_finished_payment(session, client, payment)
                except VPNUsernameTakenError:
                    logger.error("Payment %s: pre-generated username collided", payment.id)
                    await bot.send_message(
                        payment.telegram_id,
                        "⚠️ Your payment was received, but we hit a technical issue activating your "
                        "service. Please contact support with your payment date and amount.",
                    )
                    return web.Response(status=200, text="ok")
                except IBSngError as exc:
                    logger.error("Payment %s: IBSng error during activation: %s", payment.id, exc)
                    return web.Response(status=500, text="ibsng error")  # lets NOWPayments retry the IPN

            payment.status = "paid"
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            action = "renewed" if payment.purpose == "renew" else "activated"
            await bot.send_message(
                payment.telegram_id,
                f"🎉 Payment confirmed! Your service (<code>{username}</code>) has been {action}.",
            )

        elif new_status == "partially_paid":
            payment.status = "partially_paid"
            payment.paid_amount = event.paid_amount
            await session.commit()
            # Deliberately no dollar shortfall figure here: actually_paid
            # (event.paid_amount) is in the invoice's pay_currency (e.g.
            # USDT units), not USD, and computing a USD shortfall
            # accurately needs the invoice's pay_currency/pay_amount
            # conversion ratio, which this design doesn't track (out of
            # scope - see §12). The linked payment page itself shows the
            # exact remaining balance in the correct currency; inventing
            # our own possibly-wrong number here would be worse than not
            # showing one.
            await bot.send_message(
                payment.telegram_id,
                "⚠️ We received a partial payment — it wasn't quite enough to complete your order, "
                "so your service hasn't been activated yet. Tap below to finish paying the remaining "
                "balance; the page will show exactly how much is left.",
                reply_markup=_topup_keyboard(payment),
            )

        else:  # "failed" or "refunded"
            payment.status = new_status
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            if new_status == "failed":
                await bot.send_message(
                    payment.telegram_id,
                    "❌ This payment did not complete. You can start over any time from "
                    "Buy Subscription or Renew Service.",
                )
            # "refunded": recorded, no user-facing message defined for v1 - out of scope (§12).

    return web.Response(status=200, text="ok")


def _topup_keyboard(payment: Payment) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payment.invoice_url:
        builder.button(text="💰 Finish Payment", url=payment.invoice_url)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

**Top-up mechanic:** NOWPayments' hosted invoice page keeps its
underlying deposit address listening for additional funds until the
payment's own window closes — `partially_paid` is not terminal on
NOWPayments' side, it just means the total received so far is under
`price_amount`. So "finish payment" re-shows the **same** stored
`invoice_url` rather than creating a second invoice; sending the
remaining amount to the same address lets NOWPayments eventually report
`finished` on the same `provider_payment_id`. No new Payment row, no new
API call, at top-up time — simpler and matches actual NOWPayments
semantics. If real-world testing during implementation shows a
partially-paid invoice's page actually rejects further funds, that's an
implementation-time finding requiring a design revisit, not assumed here.

`app/main.py` changes: import `create_webhook_app` from `app.webhook`;
inside `main()`, between `await bot.delete_webhook(...)` and the
`try:`/`await dp.start_polling(bot)` block, add:

```python
    runner = web.AppRunner(create_webhook_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()
    logger.info("Webhook server listening on :%s", settings.webhook_port)

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
```

(`from aiohttp import web` added to `main.py`'s imports.) `docker-compose.yml`
needs a `ports:` entry added to the `bot` service, matching AloBot's own
pattern: `"${WEBHOOK_PORT:-8090}:${WEBHOOK_PORT:-8090}"`.

## 10. Bot flow: Buy Subscription

`app/bot/keyboards/buy.py`'s `buy_price_summary_keyboard` button text
changes from `"✅ Buy"` to `"₿ Pay with Crypto"` (callback_data
unchanged: `buy:confirm:<plan_id>`).

`app/bot/handlers/buy.py`'s imports gain two lines:

```python
from app.services.payments.nowpayments import NowPaymentsError, PaymentProviderNotConfiguredError
from app.services.payments.service import create_crypto_payment
```

and `app/bot/keyboards/buy.py` gains `payment_link_keyboard` to its
existing import line in `buy.py`'s handler
(`from app.bot.keyboards.buy import (buy_category_keyboard,
buy_plan_keyboard, buy_price_summary_keyboard, payment_link_keyboard)`).

`app/bot/handlers/buy.py`'s `buy_confirm_cb` — currently just validates
the plan and shows `_COMING_SOON_TEXT` — becomes:

```python
@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery) -> None:
    plan_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="purchase", plan=plan, vpn_user=None,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error("NOWPayments invoice creation failed for plan %s", plan_id)
            if callback.message is not None:
                await callback.message.edit_text(_PAYMENT_UNAVAILABLE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

    if callback.message is not None:
        await callback.message.edit_text(_PAYMENT_LINK_TEXT, reply_markup=payment_link_keyboard(payment.invoice_url))
    await callback.answer()
```

(`buy.py` needs a module-level `logger = logging.getLogger(__name__)`
and `import logging` — neither currently exists in that file since it's
never needed one before.)

`_COMING_SOON_TEXT` is **kept**, not deleted — it becomes the fallback
shown if `NOWPAYMENTS_API_KEY` is still blank (e.g. a fresh deploy before
real keys are provisioned), so the bot degrades exactly the way it does
today rather than 500ing. `NowPaymentsError` is a distinct, separate
failure — the key IS configured but the live API call itself failed
(NOWPayments down, network error, unexpected response shape) — and gets
its own message rather than silently reusing `_COMING_SOON_TEXT`, since
telling a configured-but-erroring gateway apart from a
not-yet-configured one matters for whoever is debugging a production
incident. Both new texts:

```python
_PAYMENT_LINK_TEXT = (
    "💳 <b>Complete your payment</b>\n\n"
    "Tap below to open the payment page — you'll be able to choose your "
    "coin and network there. We'll confirm automatically once payment is "
    "received; no need to come back and check."
)
_PAYMENT_UNAVAILABLE_TEXT = (
    "⚠️ We couldn't reach the payment provider right now. Please try again "
    "in a few minutes, or contact support if this keeps happening."
)
```

`payment_link_keyboard(invoice_url: str)` (new, `app/bot/keyboards/buy.py`):

```python
def payment_link_keyboard(invoice_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Open Payment Page", url=invoice_url)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

Renew Service's `renew_confirm_cb`/`renew_price_summary_keyboard` get the
identical treatment: button text → `"₿ Pay with Crypto"`,
`renew_confirm_cb` calls `create_crypto_payment(..., purpose="renew",
plan=plan, vpn_user=vpn_user)` (ownership already verified earlier in
that handler — `vpn_user` is already in scope), same
`payment_link_keyboard` reused from `app/bot/keyboards/buy.py` (no need
to duplicate it into `renew.py`'s keyboard module — a cross-module
import, same way `renew.py`'s handler already imports
`back_to_menu_keyboard` from `trial.py`'s keyboard module).

`app/bot/handlers/renew.py`'s imports gain the same lines as `buy.py`
above (`NowPaymentsError`, `PaymentProviderNotConfiguredError`,
`create_crypto_payment`, `logging`, a module-level `logger`), plus
`payment_link_keyboard` added via a new
`from app.bot.keyboards.buy import payment_link_keyboard` line (`renew.py`
currently imports nothing from `app.bot.keyboards.buy`). `renew_confirm_cb`
gets the identical `try`/`except PaymentProviderNotConfiguredError`/
`except NowPaymentsError` structure as `buy_confirm_cb` above. `renew.py`
keeps its own `_COMING_SOON_TEXT` and defines its own copies of
`_PAYMENT_LINK_TEXT`/`_PAYMENT_UNAVAILABLE_TEXT` (not cross-imports) —
matching the established convention that each flow router owns its own
copies of small text constants (the same reasoning Renew Service's own
spec gave for `_RENEW_CATEGORIES` not importing Buy's `_BUY_CATEGORIES`).

## 11. Idempotency & error handling summary

- **Duplicate IPN delivery:** guarded by `payment.status != "pending"` →
  ignore, at the single point where any status transition happens (§9).
  NOWPayments retries IPNs that don't get a 200 back, so a transient
  `IBSngError` during activation (500 response) causes a safe retry
  rather than a lost payment.
- **Signature verification:** every request to `/webhooks/crypto` is
  rejected with 401 before any DB read if the HMAC doesn't match — same
  as AloBot's proven implementation.
- **Unknown order_id:** a non-numeric or unrecognized `order_id` is
  logged and 200'd (not 400/500) — matches AloBot's precedent
  (`payment is None -> "ignored"`), since NOWPayments doesn't need to
  know or retry over a request Homeland doesn't recognize.
- **Pre-check-before-external-call ordering:** `create_vpn_user` already
  enforces its own local-then-IBSng ordering (per the
  `ibsng-xmlrpc-integration` skill); `activate_finished_payment` doesn't
  need to duplicate that, it just calls the existing function.

## 12. Out of scope for this spec

- Stripe itself — only the shared `PaymentProvider` ABC is built now;
  `stripe_provider.py` is a future spec.
- Refund automation — `refunded` IPNs are recorded (status +
  `PaymentStatusEvent` row) but trigger no automated account action
  (no auto-deprovisioning) and no user-facing message. Manual/support
  handling only, for now.
- A "check payment status" button in the bot — the IPN already pushes a
  Telegram message on every terminal status; redundant for v1.
- Canceling/expiring a stale `pending` Payment row if the user never
  completes or abandons checkout — harmless orphan rows, no cleanup job
  in this spec.
- Any change to Buy/Renew's category, tier, or price-summary screens —
  only the final confirm step changes.
- Admin visibility into payments (a "view payments" admin screen) —
  Admin Panel is a separate, already-shipped feature; extending it is a
  future spec if wanted.
- Converting `paid_amount` (crypto units) into an exact USD shortfall
  figure to show the user — needs the invoice's pay_currency/pay_amount
  conversion ratio, which this design doesn't fetch or store. §5's
  "paid amount vs expected amount, for detecting partial payments" is
  satisfied qualitatively (`Payment.status == "partially_paid"` plus the
  raw `paid_amount` for audit/support use) rather than as a precise
  dollar-denominated diff — a real dollar shortfall calculation is a
  future enhancement if NOWPayments' payload turns out to carry enough
  fields to do it correctly (worth checking during implementation, since
  the IPN payload documented in AloBot's reference may include more
  than the `actually_paid` field this spec's code samples use).
