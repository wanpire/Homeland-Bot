from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.delivery import order_delivered_keyboard
from app.bot.keyboards.trial import back_to_menu_keyboard, trial_confirm_keyboard, trial_os_keyboard, trial_protocol_keyboard
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import list_plans
from app.services.adminlog import TRIAL as LOG_TRIAL, log_event
from app.services.delivery import TRIAL, send_account_delivery
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
from app.services.tutorial_delivery import deliver_device_setup
from app.services.tutorials import is_protocol_valid_for_platform, list_platforms, list_protocols
from app.services.vpn_users import (
    TrialAlreadyUsedError,
    VPNUsernameTakenError,
    create_vpn_user,
    generate_vpn_credentials,
    has_used_trial,
)

router = Router(name="trial")

logger = logging.getLogger(__name__)

_MAX_CREATE_ATTEMPTS = 3


async def _send_trial_credentials(bot: Bot, telegram_id: int, lang: str) -> int | None:
    """The trial's credentials were generated in an earlier callback with
    nothing carried forward (no FSM state, by design - a password must
    never travel in callback_data), so they are looked up fresh here: the
    just-created VPNUser row gives the username, and IBSng re-reads the
    password it stored.

    The message itself is the shared one every delivery flow sends - see
    app/services/delivery.py. Returns its message id, or None if nothing
    was sent."""
    async with async_session_maker() as session:
        vpn_user = (
            await session.execute(
                select(VPNUser)
                .where(VPNUser.telegram_id == telegram_id, VPNUser.is_trial.is_(True))
                .order_by(VPNUser.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if vpn_user is None:
            return None
        trial_plans = await list_plans(session, category="trial")
        plan = trial_plans[0] if trial_plans else None

    password: str | None = None
    try:
        async with IBSngClient() as client:
            password = await client.get_user_password(username=vpn_user.ibsng_username)
        if password is None:
            # IBSng has no such user, or its getUserInfo response carries
            # no stored password. The account still exists, so the
            # delivery message degrades to its no-password variant rather
            # than printing a literal "None".
            logger.error(
                "IBSng returned no password for just-created trial account %r (telegram_id=%s)",
                vpn_user.ibsng_username,
                telegram_id,
            )
    except IBSngError:
        logger.exception(
            "Could not read the trial password back for %r (telegram_id=%s)",
            vpn_user.ibsng_username,
            telegram_id,
        )

    message_id = await send_account_delivery(
        bot,
        telegram_id,
        kind=TRIAL,
        plan=plan,
        data_cap_mb=vpn_user.data_cap_mb,
        username=vpn_user.ibsng_username,
        password=password,
        lang=lang,
    )
    await log_event(
        bot,
        LOG_TRIAL,
        User=str(telegram_id),
        Plan=plan.name if plan is not None else "Trial",
        Account=vpn_user.ibsng_username,
    )
    return message_id


@router.callback_query(F.data == "menu:trial")
async def trial_entry_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        already_used = await has_used_trial(session, callback.from_user.id)

    if callback.message is None:
        await callback.answer()
        return
    if already_used:
        await show_screen(callback.message, t("trial_already_used", lang), back_to_menu_keyboard(lang))
    else:
        await show_screen(callback.message, t("trial_confirm_prompt", lang), trial_confirm_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data == "trial:confirm")
async def trial_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    telegram_id = callback.from_user.id

    # "trial:confirm" is a bare callback_data string: an old message's
    # button still works, so this callback can arrive without ever
    # passing through trial_entry_cb's eligibility check. Re-check here
    # rather than trusting the path the user took to get here.
    async with async_session_maker() as session:
        if await has_used_trial(session, telegram_id):
            if callback.message is not None:
                await callback.message.edit_text(t("trial_already_used", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

    async with async_session_maker() as session:
        trial_plans = await list_plans(session, category="trial")
    trial_plan = trial_plans[0]

    vpn_user = None
    last_error: str | None = None
    for _attempt in range(_MAX_CREATE_ATTEMPTS):
        username, password = generate_vpn_credentials()
        async with async_session_maker() as session, IBSngClient() as client:
            try:
                vpn_user = await create_vpn_user(
                    session, client,
                    telegram_id=telegram_id, username=username, password=password,
                    group_name=trial_plan.group_name, data_cap_mb=trial_plan.data_cap_mb,
                    plan_id=trial_plan.id, is_trial=True,
                )
                break
            except TrialAlreadyUsedError:
                # Retrying is pointless (and, before the pre-check landed,
                # actively harmful): the blocker is the telegram_id, not
                # the generated username, so a fresh username can never
                # make the next attempt succeed.
                last_error = "trial_used"
                break
            except (VPNUsernameTakenError, IBSngUserExistsError):
                last_error = "taken"
                continue
            except IBSngError:
                last_error = "ibsng"
                break

    if vpn_user is None:
        if callback.message is not None:
            # Only "trial_used" actually means the trial is spent. Both
            # "taken" (every attempt lost a genuine username collision)
            # and "ibsng" (a real IBSng failure) are transient - telling
            # an eligible user their trial was "already used" in those
            # cases would be flatly wrong.
            text = t("trial_already_used", lang) if last_error == "trial_used" else t("trial_create_failed", lang)
            await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return

    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(t("protocol_prompt", lang), reply_markup=trial_protocol_keyboard(protocols, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("trial:protocol:"))
async def trial_protocol_cb(callback: CallbackQuery, lang: str) -> None:
    """Step 3: the device, asked for every protocol before anything is
    sent, so the setup that follows the credentials is for that device
    only and never asks again."""
    try:
        protocol_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    async with async_session_maker() as session:
        platforms = await list_platforms(session)
    if callback.message is not None:
        await callback.message.edit_text(
            t("platform_prompt", lang),
            reply_markup=trial_os_keyboard(protocol_id, platforms, lang),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("trial:os:"))
async def trial_os_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    try:
        protocol_id, platform_id = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await _deliver_trial(callback, protocol_id=protocol_id, platform_id=platform_id, lang=lang)


@router.callback_query(F.data.startswith("trial:platform:"))
async def trial_platform_cb(callback: CallbackQuery, lang: str) -> None:
    """The previous flow's L2TP-only device buttons. Still honoured,
    because a message carrying them may sit in a customer's history."""
    try:
        platform_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    l2tp = next((p for p in protocols if p.label.strip().lower() == "l2tp"), None)
    if l2tp is None:
        await callback.answer()
        return
    await _deliver_trial(callback, protocol_id=l2tp.id, platform_id=platform_id, lang=lang)


async def _deliver_trial(callback: CallbackQuery, *, protocol_id: int, platform_id: int, lang: str) -> None:
    """Steps 4-6, each its own message: credentials (no buttons), then the
    chosen device's setup material, then the Tutorial/main-menu pair on
    whichever of those came last."""
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)
        platform = await session.get(TutorialPlatform, platform_id)
    if protocol is None or platform is None:
        await callback.answer()
        return

    if not is_protocol_valid_for_platform(platform.label, protocol.label):
        # Checked before the credentials go out, since nothing after them
        # can be taken back. The picker stays so Back still reaches the
        # protocol step.
        await callback.bot.send_message(telegram_id, t("android_l2tp_unsupported", lang))
        await callback.answer()
        return

    if callback.message is not None:
        # One device per picker: a second tap would resend the whole
        # sequence. Two taps racing each other both get here, but only one
        # can strip the keyboard - Telegram refuses the other as "not
        # modified", and that one stops.
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                await callback.answer()
                return
            logger.warning("Could not disarm the trial device picker for %s: %s", telegram_id, exc)

    last_message_id = await _send_trial_credentials(callback.bot, telegram_id, lang)
    if last_message_id is None:
        await callback.answer()
        return
    async with async_session_maker() as session:
        setup_message_id = await deliver_device_setup(
            callback.bot, telegram_id, session, protocol=protocol, platform=platform, lang=lang
        )
    try:
        await callback.bot.edit_message_reply_markup(
            chat_id=telegram_id,
            message_id=setup_message_id or last_message_id,
            reply_markup=order_delivered_keyboard(lang),
        )
    except TelegramAPIError:
        # Everything that matters has been delivered; the buttons are a
        # convenience and the main menu is still one /start away.
        logger.warning("Could not attach the closing buttons to %s's trial delivery", telegram_id, exc_info=True)
    await callback.answer()


@router.callback_query(F.data == "trial:back_to_protocol")
async def trial_back_to_protocol_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(t("protocol_prompt", lang), reply_markup=trial_protocol_keyboard(protocols, lang))
    await callback.answer()
