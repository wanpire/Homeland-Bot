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

_MAX_POSTGRES_INT = 2**31 - 1


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
    # asyncpg.DataError - the same class of bug the Renew Service
    # feature's final review found and fixed for callback_data ids.
    # order_id is just as attacker-reachable here: NOWPayments echoes
    # back whatever order_id was sent, but nothing stops a malicious
    # actor from POSTing directly to this public endpoint with a
    # crafted body.
    order_id_value: int | None = None
    if event.order_id.isdigit() and 0 < int(event.order_id) <= _MAX_POSTGRES_INT:
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
        # is a no-op.
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
            # conversion ratio, which this design doesn't track. The
            # linked payment page itself shows the exact remaining
            # balance in the correct currency.
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
            # "refunded": recorded, no user-facing message defined for v1.

    return web.Response(status=200, text="ok")


def _topup_keyboard(payment: Payment) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payment.invoice_url:
        builder.button(text="💰 Finish Payment", url=payment.invoice_url)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
