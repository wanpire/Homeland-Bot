from __future__ import annotations

import datetime as dt
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from sqlalchemy import select

from app.db.models.payment import Payment
from app.db.models.payment_status_event import PaymentStatusEvent
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.bot_users import get_language
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
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

# Only these are actually terminal. "partially_paid" is deliberately
# excluded: on NOWPayments' side the same invoice/deposit address keeps
# accepting funds after a partially_paid IPN, until a later "finished" IPN
# for the SAME payment reports it fully paid - spec §9's top-up mechanic.
_TERMINAL_STATUSES = {"paid", "failed", "refunded"}

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
        payment = (
            await session.get(Payment, order_id_value, with_for_update=True)
            if order_id_value is not None
            else None
        )
        if payment is None:
            return web.Response(status=200, text="ignored")

        session.add(PaymentStatusEvent(
            payment_id=payment.id, raw_status=event.raw_status, paid_amount=event.paid_amount,
        ))
        await session.commit()

        if event.raw_status not in _FINAL_STATUSES:
            return web.Response(status=200, text="ok")  # progress state, nothing to do

        # Idempotency guard, under a FRESH row lock: re-fetch WITH FOR
        # UPDATE right here, immediately before the decision, rather than
        # reusing the lock from the SELECT above (which the audit-event
        # commit already released). A second, genuinely concurrent
        # delivery for the same payment blocks on this SELECT until this
        # transaction commits below, so it always sees this decision's
        # outcome rather than racing it. The `payment` object is already
        # in this session's identity map from the session.get() call
        # above, so without populate_existing=True this SELECT would just
        # hand back that SAME cached object with its stale in-memory
        # .status, silently skipping the refresh from the database that
        # the whole point of this re-fetch depends on - do not drop it as
        # "redundant".
        #
        # Only a truly TERMINAL status blocks further processing - "paid",
        # "failed", "refunded". "pending" and "partially_paid" both stay
        # open: partially_paid is NOT terminal on NOWPayments' side (the
        # same invoice keeps accepting funds to the same address until
        # fully paid), so a later "finished" IPN for a partially_paid
        # payment must still be able to activate it - this is exactly
        # spec §9's documented top-up mechanic, which the previous
        # ("!= pending") gate silently broke.
        payment = (
            await session.execute(
                select(Payment)
                .where(Payment.id == order_id_value)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if payment.status in _TERMINAL_STATUSES:
            return web.Response(status=200, text="ignored")

        new_status = _FINAL_STATUSES[event.raw_status]

        if new_status == "paid":
            async with IBSngClient() as client:
                try:
                    username = await activate_finished_payment(session, client, payment)
                except VPNUsernameTakenError:
                    logger.error("Payment %s: pre-generated username collided", payment.id)
                    lang = (await get_language(session, payment.telegram_id)) or "en"
                    await _notify_activation_technical_issue(bot, payment, lang)
                    return web.Response(status=200, text="ok")
                except IBSngUserExistsError:
                    # Permanent failure - an orphaned IBSng-side account
                    # (e.g. from an earlier crash) with no matching local
                    # VPNUser row. Retrying can never fix this; a human
                    # needs to look at it, so no 500/retry here.
                    logger.error(
                        "Payment %s: IBSng account already exists (orphaned account)", payment.id,
                    )
                    lang = (await get_language(session, payment.telegram_id)) or "en"
                    await _notify_activation_technical_issue(bot, payment, lang)
                    return web.Response(status=200, text="ok")
                except IBSngError as exc:
                    logger.error("Payment %s: IBSng error during activation: %s", payment.id, exc)
                    return web.Response(status=500, text="ibsng error")  # lets NOWPayments retry the IPN

            payment.status = "paid"
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            action_key = "action_renewed" if payment.purpose == "renew" else "action_activated"
            lang = (await get_language(session, payment.telegram_id)) or "en"
            await bot.send_message(
                payment.telegram_id,
                t("payment_confirmed", lang, username=username, action=t(action_key, lang)),
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
            lang = (await get_language(session, payment.telegram_id)) or "en"
            await bot.send_message(
                payment.telegram_id,
                t("partial_payment", lang),
                reply_markup=_topup_keyboard(payment, lang),
            )

        else:  # "failed" or "refunded"
            payment.status = new_status
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            if new_status == "failed":
                lang = (await get_language(session, payment.telegram_id)) or "en"
                await bot.send_message(payment.telegram_id, t("payment_failed", lang))
            # "refunded": recorded, no user-facing message defined for v1.

    return web.Response(status=200, text="ok")


async def _notify_activation_technical_issue(bot: Bot, payment: Payment, lang: str) -> None:
    """Notify the user that their payment was received but activation hit
    a permanent technical issue. Tolerates the user having blocked the
    bot - that failure must never prevent the handler's 200 response,
    since NOWPayments would otherwise retry forever for a situation
    retrying can never fix."""
    try:
        await bot.send_message(payment.telegram_id, t("activation_technical_issue", lang))
    except TelegramForbiddenError:
        logger.warning(
            "Payment %s: could not notify user %s - bot is blocked", payment.id, payment.telegram_id,
        )


def _topup_keyboard(payment: Payment, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payment.invoice_url:
        builder.button(text=t("finish_payment_button", lang), url=payment.invoice_url)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
