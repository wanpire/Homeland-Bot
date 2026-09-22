"""Recovery for paid invoices that never finished activating.

A callback can be verified and accepted and STILL leave the buyer
without their service: if IBSng is unreachable at that moment the
handler answers 500 to ask Plisio to retry, and once Plisio stops
retrying the order is stranded with money taken and nothing delivered.
That happened in production on 2026-09-22 (payment 16).

This job closes that hole. It asks Plisio directly about every pending
payment and finishes the ones Plisio calls completed, through the same
confirm_paid_payment the callback uses - so there is no second
provisioning path to keep in step.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from sqlalchemy import select

from app.db.models.payment import Payment
from app.db.session import async_session_maker
from app.services.payments.confirmation import ACTIVATED, TRANSIENT, confirm_paid_payment
from app.services.payments.plisio import PaymentProviderNotConfiguredError, PlisioError, get_invoice_status

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 10 * 60

#: How far back to look. A Plisio invoice that has not been paid within
#: this window never will be, and re-querying it forever would be noise.
MAX_AGE_HOURS = 72

#: Only this provider's payments can be looked up on Plisio.
PROVIDER = "plisio"

#: Statuses on Plisio's side that mean the money arrived in full.
_PAID_STATUSES = {"completed"}

#: Payment.status values still worth chasing. "partially_paid" is
#: included because the buyer can top the same invoice up to completion.
_OPEN_STATUSES = ("pending", "partially_paid")


async def reconcile_pending_payments(bot: Bot) -> dict[str, int]:
    """One pass. Returns counts for logging and the admin screen."""
    counts = {"checked": 0, "activated": 0, "still_open": 0, "errors": 0}

    async with async_session_maker() as session:
        result = await session.execute(
            select(Payment.id).where(
                Payment.status.in_(_OPEN_STATUSES),
                # Only Plisio's own orders: rows from the NOWPayments era
                # carry that provider's numeric ids, which Plisio answers
                # with a 404 forever.
                Payment.provider == PROVIDER,
                Payment.provider_payment_id.is_not(None),
                Payment.created_at >= _cutoff(),
            )
        )
        payment_ids = [row[0] for row in result.all()]

    for payment_id in payment_ids:
        counts["checked"] += 1
        try:
            if await _reconcile_one(bot, payment_id):
                counts["activated"] += 1
            else:
                counts["still_open"] += 1
        except PaymentProviderNotConfiguredError:
            logger.error("Reconcile: PLISIO_SECRET_KEY is not set - cannot check payment %s", payment_id)
            counts["errors"] += 1
        except PlisioError as exc:
            logger.error("Reconcile: Plisio lookup failed for payment %s: %s", payment_id, exc)
            counts["errors"] += 1
        except Exception:
            # One bad row must never abort the sweep for the others.
            logger.exception("Reconcile: unexpected failure on payment %s", payment_id)
            counts["errors"] += 1

    if counts["activated"] or counts["errors"]:
        logger.warning("Reconcile pass finished: %s", counts)
    else:
        logger.info("Reconcile pass finished: %s", counts)
    return counts


def _cutoff():  # type: ignore[no-untyped-def]
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=MAX_AGE_HOURS)


async def _reconcile_one(bot: Bot, payment_id: int) -> bool:
    """True when this pass activated the payment."""
    async with async_session_maker() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None or payment.provider_payment_id is None:
            return False
        provider_payment_id = payment.provider_payment_id

    status = await get_invoice_status(provider_payment_id)
    if status is None or status.lower() not in _PAID_STATUSES:
        return False

    async with async_session_maker() as session:
        # Re-read under a row lock: a callback may have activated this
        # payment between the query above and now, and provisioning it
        # twice would create a second IBSng account for one order.
        payment = (
            await session.execute(
                select(Payment)
                .where(Payment.id == payment_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if payment is None or payment.status not in _OPEN_STATUSES:
            return False

        logger.warning(
            "Reconcile: payment %s is '%s' on Plisio but still '%s' here - activating now",
            payment.id, status, payment.status,
        )
        result = await confirm_paid_payment(bot, session, payment)

    if result.outcome == ACTIVATED:
        logger.warning("Reconcile: payment %s activated as %s", payment_id, result.username)
        return True
    if result.outcome == TRANSIENT:
        logger.error(
            "Reconcile: payment %s still cannot be activated (%s) - will retry next pass",
            payment_id, result.detail,
        )
    return False


async def run_reconcile_loop(bot: Bot) -> None:
    """Background sweep, started alongside the reminder loop."""
    while True:
        try:
            await reconcile_pending_payments(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reconcile loop pass failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
