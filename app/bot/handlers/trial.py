from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.handlers.handover import platform_back_callback, run_handover
from app.bot.keyboards.handover import handover_platform_keyboard
from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.trial import back_to_menu_keyboard, trial_confirm_keyboard
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import list_plans
from app.services.handover import TRIAL_SOURCE, load_handover_account
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import (
    TrialAlreadyUsedError,
    VPNUsernameTakenError,
    create_vpn_user,
    generate_vpn_credentials,
    has_used_trial,
)

router = Router(name="trial")

_MAX_CREATE_ATTEMPTS = 3


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

    # Step 1 of the shared handover sequence (app/services/handover.py):
    # device first, then protocol, then credentials and setup.
    await _show_device_picker(callback, vpn_user.id, lang)
    await callback.answer()


async def _show_device_picker(callback: CallbackQuery, vpn_user_id: int, lang: str) -> None:
    async with async_session_maker() as session:
        platforms = await list_platforms(session)
    if callback.message is not None:
        await callback.message.edit_text(
            t("platform_prompt", lang),
            reply_markup=handover_platform_keyboard(
                TRIAL_SOURCE, vpn_user_id, platforms, lang, back_callback=platform_back_callback(TRIAL_SOURCE)
            ),
        )


async def _latest_trial_id(telegram_id: int) -> int | None:
    """The legacy callbacks below carry no account id; they always meant
    the user's most recent trial."""
    async with async_session_maker() as session:
        return (
            await session.execute(
                select(VPNUser.id)
                .where(VPNUser.telegram_id == telegram_id, VPNUser.is_trial.is_(True))
                .order_by(VPNUser.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


# --- Legacy callbacks -------------------------------------------------
# Buttons from the previous protocol-first flow may still sit in a
# customer's chat history, so they keep working: the two that name a
# device deliver through the shared sequence, the two that do not open
# its device picker.


@router.callback_query(F.data.startswith("trial:protocol:") | (F.data == "trial:back_to_protocol"))
async def trial_legacy_picker_cb(callback: CallbackQuery, lang: str) -> None:
    vpn_user_id = await _latest_trial_id(callback.from_user.id)
    if vpn_user_id is not None:
        await _show_device_picker(callback, vpn_user_id, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("trial:os:"))
async def trial_legacy_os_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    try:
        protocol_id, platform_id = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await _legacy_deliver(callback, protocol_id=protocol_id, platform_id=platform_id, lang=lang)


@router.callback_query(F.data.startswith("trial:platform:"))
async def trial_legacy_platform_cb(callback: CallbackQuery, lang: str) -> None:
    """The oldest flow's L2TP-only device buttons."""
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
    await _legacy_deliver(callback, protocol_id=l2tp.id, platform_id=platform_id, lang=lang)


async def _legacy_deliver(callback: CallbackQuery, *, protocol_id: int, platform_id: int, lang: str) -> None:
    vpn_user_id = await _latest_trial_id(callback.from_user.id)
    async with async_session_maker() as session:
        account = (
            await load_handover_account(session, TRIAL_SOURCE, vpn_user_id, callback.from_user.id)
            if vpn_user_id is not None
            else None
        )
        protocol = await session.get(TutorialProtocol, protocol_id)
        platform = await session.get(TutorialPlatform, platform_id)
    if account is None or protocol is None or platform is None:
        await callback.answer()
        return
    await run_handover(callback, account, protocol=protocol, platform=platform, lang=lang)
