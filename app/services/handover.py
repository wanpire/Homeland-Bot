"""The ONE handover sequence: how a customer receives a working account.

Trial, purchase and renewal all run it:

- device (iOS / Android / Windows / macOS);
- protocol, offering only what that device supports and skipped when
  exactly one is left (Android has no L2TP, so it goes straight to
  OpenVPN) - see `protocols_for_platform`;
- credentials, the shared message from app/services/delivery.py;
- that device's setup material only (`deliver_device_setup`);
- the Tutorial/main-menu pair, on whichever message came last.

A trial runs them in that order. A paid order sends the credentials
first, the moment the payment is activated, so a customer who never
taps a picker still has a working account in hand; its pickers then
lead to the setup alone.

The pickers live in app/bot/handlers/handover.py (`ho:<source>:<ref>:…`).
A source says where the account comes from: TRIAL_SOURCE with a
`vpn_users.id`, PAID_SOURCE with a `payments.id`. The password is never
put in callback data; it is read from the payment row or back from IBSng
when the credentials go out.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.delivery import order_delivered_keyboard
from app.bot.keyboards.handover import handover_platform_keyboard
from app.db.models.payment import Payment
from app.db.models.plan import Plan
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.adminlog import TRIAL as LOG_TRIAL, log_event
from app.services.catalog import get_plan, list_plans
from app.services.delivery import PURCHASE, RENEWAL, TRIAL, send_account_delivery
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.tutorial_delivery import deliver_device_setup
from app.services.tutorials import is_protocol_valid_for_platform, list_platforms

logger = logging.getLogger(__name__)

TRIAL_SOURCE = "t"
PAID_SOURCE = "p"


@dataclass(frozen=True)
class HandoverAccount:
    """Everything the credentials message needs except the password,
    which is only fetched once the customer has chosen their setup."""

    source: str
    ref: int
    kind: str
    plan: Plan | None
    data_cap_mb: int
    username: str
    fallback_plan_name: str = "—"
    stored_password: str | None = None

    @property
    def credentials_sent_up_front(self) -> bool:
        """A paid order's credentials go out at payment time, before the
        pickers; a trial's follow them."""
        return self.source == PAID_SOURCE


async def load_handover_account(
    session: AsyncSession, source: str, ref: int, telegram_id: int
) -> HandoverAccount | None:
    """None unless the row exists and belongs to the tapping user; a paid
    order must also be paid and provisioned. Checked on every step, since
    callback data is just a string anyone could send."""
    if source == TRIAL_SOURCE:
        vpn_user = await session.get(VPNUser, ref)
        if vpn_user is None or vpn_user.telegram_id != telegram_id or not vpn_user.is_trial:
            return None
        trial_plans = await list_plans(session, category="trial")
        return HandoverAccount(
            source=source, ref=ref, kind=TRIAL,
            plan=trial_plans[0] if trial_plans else None,
            data_cap_mb=vpn_user.data_cap_mb,
            username=vpn_user.ibsng_username,
        )

    if source == PAID_SOURCE:
        payment = await session.get(Payment, ref)
        if (
            payment is None
            or payment.telegram_id != telegram_id
            or payment.status != "paid"
            or payment.vpn_user_id is None
        ):
            return None
        vpn_user = await session.get(VPNUser, payment.vpn_user_id)
        if vpn_user is None:
            return None
        return HandoverAccount(
            source=source, ref=ref,
            kind=RENEWAL if payment.purpose == "renew" else PURCHASE,
            plan=await get_plan(session, payment.plan_id) if payment.plan_id is not None else None,
            # The snapshot on the payment, never the plan's current value:
            # an admin editing the catalog mid-payment must not change what
            # this buyer was actually sold.
            data_cap_mb=payment.data_cap_mb,
            username=vpn_user.ibsng_username,
            fallback_plan_name=payment.group_name,
            # A purchase carries the password generated with its payment; a
            # renewal keeps the account's existing one, read back later.
            stored_password=payment.ibsng_password,
        )

    return None


async def send_handover_prompt(bot: Bot, telegram_id: int, session: AsyncSession, *, payment_id: int, lang: str) -> None:
    """A paid order's handover opening, sent once the payment is
    activated: the credentials straight away (a paying customer must
    never depend on a later tap to learn them), then the device picker
    that leads to the setup. Never raises: the service is provisioned by
    now, so nothing here may make the payment look failed upstream."""
    account = await load_handover_account(session, PAID_SOURCE, payment_id, telegram_id)
    if account is None:
        logger.error("Handover: payment %s is not a paid, provisioned order of %s", payment_id, telegram_id)
        return
    credentials_message_id = await _send_credentials(bot, telegram_id, account, lang)
    if credentials_message_id is None:
        return  # bot blocked - nothing else will get through either

    platforms = await list_platforms(session)
    if not platforms:
        logger.error("Handover: no active platforms configured; payment %s ends at the credentials", payment_id)
        await _attach_closing_pair(bot, telegram_id, credentials_message_id, lang)
        return
    try:
        await bot.send_message(
            telegram_id,
            t("platform_prompt", lang),
            reply_markup=handover_platform_keyboard(PAID_SOURCE, payment_id, platforms, lang, back_callback=None),
        )
    except TelegramForbiddenError:
        logger.warning("Handover prompt for payment %s not sent to %s - bot is blocked", payment_id, telegram_id)


async def deliver_handover(
    bot: Bot,
    telegram_id: int,
    account: HandoverAccount,
    *,
    protocol: TutorialProtocol,
    platform: TutorialPlatform,
    lang: str,
    claim: Callable[[], Awaitable[bool]] | None = None,
    anchor_message_id: int | None = None,
) -> bool:
    """The steps after the pickers: credentials (unless they already went
    out at payment time), the device's setup, and the closing pair. The
    compatibility gate runs first, because nothing after it can be taken
    back. `claim` then runs (the handler uses it to disarm the picker);
    returning False means another tap already won, and nothing is sent.
    `anchor_message_id` (the picker) carries the pair when a paid order's
    device has no setup material to send. Returns whether anything went
    out."""
    if not is_protocol_valid_for_platform(platform.label, protocol.label):
        await bot.send_message(telegram_id, t("android_l2tp_unsupported", lang))
        return False
    if claim is not None and not await claim():
        return False

    last_message_id = anchor_message_id
    if not account.credentials_sent_up_front:
        last_message_id = await _send_credentials(bot, telegram_id, account, lang)
        if last_message_id is None:
            return False
    async with async_session_maker() as session:
        setup_message_id = await deliver_device_setup(
            bot, telegram_id, session, protocol=protocol, platform=platform, lang=lang
        )
    closing_message_id = setup_message_id or last_message_id
    if closing_message_id is not None:
        await _attach_closing_pair(bot, telegram_id, closing_message_id, lang)
    return True


async def _send_credentials(bot: Bot, telegram_id: int, account: HandoverAccount, lang: str) -> int | None:
    message_id = await send_account_delivery(
        bot,
        telegram_id,
        kind=account.kind,
        plan=account.plan,
        data_cap_mb=account.data_cap_mb,
        username=account.username,
        password=await _read_password(account, telegram_id),
        lang=lang,
        fallback_plan_name=account.fallback_plan_name,
    )
    if account.kind == TRIAL:
        # Paid orders are logged at activation (payments/confirmation.py);
        # a trial is logged when it is actually handed over.
        await log_event(
            bot,
            LOG_TRIAL,
            User=str(telegram_id),
            Plan=account.plan.name if account.plan is not None else "Trial",
            Account=account.username,
        )
    return message_id


async def _read_password(account: HandoverAccount, telegram_id: int) -> str | None:
    """A failure here must never fail the handover - the account exists
    either way, and a missing password degrades to the contact-support
    variant of the message rather than printing a literal "None"."""
    if account.stored_password:
        return account.stored_password
    try:
        async with IBSngClient() as client:
            password = await client.get_user_password(username=account.username)
    except IBSngError:
        logger.exception("Could not read the password back for %r (telegram_id=%s)", account.username, telegram_id)
        return None
    if password is None:
        logger.error("IBSng returned no password for %r (telegram_id=%s)", account.username, telegram_id)
    return password


async def _attach_closing_pair(bot: Bot, telegram_id: int, message_id: int, lang: str) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=telegram_id, message_id=message_id, reply_markup=order_delivered_keyboard(lang)
        )
    except TelegramAPIError:
        # Everything that matters has been delivered; the buttons are a
        # convenience and the main menu is still one /start away.
        logger.warning("Could not attach the closing buttons to %s's handover", telegram_id, exc_info=True)
