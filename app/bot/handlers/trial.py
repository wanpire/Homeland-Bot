from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.trial import back_to_menu_keyboard, trial_confirm_keyboard, trial_platform_keyboard, trial_protocol_keyboard
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import list_plans
from app.services.delivery import TRIAL, send_account_delivery
from app.services.openvpn_setup import send_openvpn_setup
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
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


async def _send_trial_credentials(bot: Bot, telegram_id: int, lang: str) -> None:
    """The trial's credentials were generated in an earlier callback with
    nothing carried forward (no FSM state, by design - a password must
    never travel in callback_data), so they are looked up fresh here: the
    just-created VPNUser row gives the username, and IBSng re-reads the
    password it stored.

    The message itself is the shared one every delivery flow sends - see
    app/services/delivery.py."""
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
            return
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

    await send_account_delivery(
        bot,
        telegram_id,
        kind=TRIAL,
        plan=plan,
        data_cap_mb=vpn_user.data_cap_mb,
        username=vpn_user.ibsng_username,
        password=password,
        lang=lang,
    )


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
    protocol_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)

    if protocol is not None and protocol.label.strip().lower() == "openvpn":
        # Credentials first, then the setup step: the account details are
        # what the customer is waiting for, and the shared step always
        # succeeds, so there is nothing left to gate them on.
        await _send_trial_credentials(callback.bot, callback.from_user.id, lang)
        async with async_session_maker() as session:
            await send_openvpn_setup(callback.bot, callback.from_user.id, session, lang=lang)
        await callback.answer()
        return

    async with async_session_maker() as session:
        platforms = await list_platforms(session)
    if callback.message is not None:
        await callback.message.edit_text(
            t("platform_prompt", lang),
            reply_markup=trial_platform_keyboard(platforms, lang),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("trial:platform:"))
async def trial_platform_cb(callback: CallbackQuery, lang: str) -> None:
    platform_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    l2tp = next(p for p in protocols if p.label.strip().lower() == "l2tp")

    async with async_session_maker() as session:
        delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=l2tp.id, platform_id=platform_id, lang=lang)
    if delivered:
        await _send_trial_credentials(callback.bot, callback.from_user.id, lang)
    await callback.answer()


@router.callback_query(F.data == "trial:back_to_protocol")
async def trial_back_to_protocol_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(t("protocol_prompt", lang), reply_markup=trial_protocol_keyboard(protocols, lang))
    await callback.answer()
