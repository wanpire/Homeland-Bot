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
    """deliver_setup (Task 3) deliberately does NOT send the account's
    username/password - it's a generic (platform, protocol) -> content
    function reused later by Buy/Renew, which won't always want the
    same trial-specific closing message. The credentials themselves were
    generated back in trial_confirm_cb, a separate callback invocation
    with nothing carried forward (no FSM state, by design - see the
    spec's rationale for not putting a password in callback_data), so
    they're looked up fresh here: the just-created VPNUser row gives the
    username, and IBSngClient.get_user_password re-reads the password
    IBSng already has stored for it (same accessor AloBot's own renew
    flow uses to re-show an existing password)."""
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

    try:
        async with IBSngClient() as client:
            password = await client.get_user_password(username=vpn_user.ibsng_username)

        if password is None:
            # get_user_password returns None when IBSng has no such user,
            # or when its getUserInfo response carries no stored
            # normal_password - either way there is nothing to show, and
            # rendering it would print a literal "None" as the password.
            logger.error(
                "IBSng returned no password for just-created trial account %r (telegram_id=%s)",
                vpn_user.ibsng_username,
                telegram_id,
            )
            await bot.send_message(telegram_id, t("trial_credentials_unavailable", lang))
            return

        await bot.send_message(
            telegram_id, t("trial_ready", lang, username=vpn_user.ibsng_username, password=password)
        )
    except Exception:
        # The account exists but we couldn't hand over its credentials.
        # Failing silently here would leave the user with a delivered
        # guide, a real trial account, and no way to log in - so tell
        # them explicitly to contact support (there is no self-service
        # "show me my credentials again" flow yet; that belongs to the
        # My Services plan).
        logger.exception(
            "Could not deliver trial credentials for %r (telegram_id=%s)",
            vpn_user.ibsng_username,
            telegram_id,
        )
        try:
            await bot.send_message(telegram_id, t("trial_credentials_unavailable", lang))
        except Exception:
            logger.exception("Could not deliver the credentials-unavailable message to telegram_id=%s", telegram_id)


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
        async with async_session_maker() as session:
            delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=protocol_id, platform_id=None, lang=lang)
        if delivered:
            await _send_trial_credentials(callback.bot, callback.from_user.id, lang)
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
