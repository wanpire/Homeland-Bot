"""Turning a paid invoice into a provisioned service - the ONE place that
does it, shared by the callback handler and the reconciler.

Extracted from app/webhook.py when a live payment showed why a second
caller is needed: the callback arrived, verified and was processed
correctly, but IBSng was unreachable at that moment, so activation
failed. The handler returned 500 to ask Plisio to retry, Plisio stopped
retrying, and a fully paid order was stranded with no way back. The
reconciler re-drives exactly this function rather than reimplementing it.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import Payment
from app.i18n.texts import t
from app.services.adminlog import PURCHASE, RENEWAL, log_event
from app.services.bot_users import get_language
from app.services.handover import send_handover_prompt
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
from app.services.payments.service import activate_finished_payment
from app.services.vpn_users import VPNUsernameTakenError

logger = logging.getLogger(__name__)

#: Activated successfully; the buyer has been told.
ACTIVATED = "activated"
#: Permanently stuck - a human has to look. Retrying cannot help, so a
#: caller must NOT ask the provider to redeliver.
BLOCKED = "blocked"
#: Transient failure (IBSng unreachable). The payment stays pending and
#: another attempt - a provider retry or the reconciler - can still
#: activate it.
TRANSIENT = "transient"


@dataclass
class ConfirmResult:
    outcome: str
    username: str | None = None
    detail: str | None = None


async def confirm_paid_payment(bot: Bot, session: AsyncSession, payment: Payment) -> ConfirmResult:
    """Provision the service for an already-verified paid invoice, mark
    the payment paid, and tell the buyer. The caller owns the row lock
    and the decision about what to answer the provider."""
    try:
        async with IBSngClient() as client:
            username = await activate_finished_payment(session, client, payment)
    except VPNUsernameTakenError:
        logger.error("Payment %s: pre-generated username collided", payment.id)
        await _notify_activation_technical_issue(bot, session, payment)
        return ConfirmResult(BLOCKED, detail="username collision")
    except IBSngUserExistsError:
        # Permanent: an orphaned IBSng-side account with no matching local
        # VPNUser row. Retrying can never fix this; a human must.
        logger.error("Payment %s: IBSng account already exists (orphaned account)", payment.id)
        await _notify_activation_technical_issue(bot, session, payment)
        return ConfirmResult(BLOCKED, detail="orphaned IBSng account")
    except IBSngError as exc:
        # Transient: IBSng unreachable or erroring. The payment stays
        # pending so a retry or the reconciler can finish the job.
        logger.error("Payment %s: IBSng error during activation: %s", payment.id, exc)
        return ConfirmResult(TRANSIENT, detail=str(exc))

    payment.status = "paid"
    payment.resolved_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()

    await _send_delivery_message(bot, session, payment, username)
    # Logged here rather than in the webhook so a payment recovered by
    # the reconciler is logged too - those are the ones an admin most
    # wants to see.
    await log_event(
        bot,
        RENEWAL if payment.purpose == "renew" else PURCHASE,
        User=str(payment.telegram_id),
        Plan=payment.group_name,
        Amount=f"${payment.amount_usd}",
        Provider=payment.provider,
        Account=username,
    )
    return ConfirmResult(ACTIVATED, username=username)


async def _send_delivery_message(bot: Bot, session: AsyncSession, payment: Payment, username: str) -> None:
    """The shared handover sequence (app/services/handover.py): the
    credentials now, then the device picker that leads to the setup."""
    lang = (await get_language(session, payment.telegram_id)) or "en"
    await send_handover_prompt(bot, payment.telegram_id, session, payment_id=payment.id, lang=lang)


async def _notify_activation_technical_issue(bot: Bot, session: AsyncSession, payment: Payment) -> None:
    """Tell the buyer their payment landed but activation hit a permanent
    problem. Tolerates a blocked bot: that must never stop the caller
    answering the provider, which would otherwise retry forever."""
    lang = (await get_language(session, payment.telegram_id)) or "en"
    try:
        await bot.send_message(payment.telegram_id, t("activation_technical_issue", lang))
    except TelegramForbiddenError:
        logger.warning(
            "Payment %s: could not notify user %s - bot is blocked", payment.id, payment.telegram_id
        )
