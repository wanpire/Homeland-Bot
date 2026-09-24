from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.myservices import (
    account_menu_keyboard,
    back_to_account_keyboard,
    myservices_detail_keyboard,
    myservices_empty_keyboard,
    myservices_list_keyboard,
    myservices_platform_keyboard,
    myservices_protocol_keyboard,
    myservices_root_keyboard,
    password_confirm_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.account_view import build_account_info, credential_lines
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.openvpn_setup import send_openvpn_setup
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import (
    ForeignGroupError,
    PasswordChangeCooldownError,
    cooldown_days_left,
    get_owned_vpn_user,
    list_services_with_status,
    password_change_remaining,
    reset_vpn_password,
)

router = Router(name="myservices")

logger = logging.getLogger(__name__)


def _vpn_user_id(data: str) -> int | None:
    """Callback data is untrusted: a malformed or out-of-range id (Postgres
    int4) reads as not found rather than raising."""
    try:
        value = int(data.split(":")[2])
    except (IndexError, ValueError):
        return None
    return value if 0 < value < 2**31 else None


async def _not_found(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        await callback.message.edit_text(t("myservices_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data == "menu:myservices")
async def myservices_root_cb(callback: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    if callback.message is not None:
        await show_screen(callback.message, t("myservices_root", lang), myservices_root_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data == "myservices:list")
async def myservices_list_cb(callback: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as session, IBSngClient() as client:
        rows = await list_services_with_status(session, client, callback.from_user.id)

    if callback.message is not None:
        if rows:
            await show_screen(callback.message, t("myservices_heading", lang), myservices_list_keyboard(rows, lang))
        else:
            await show_screen(callback.message, t("myservices_empty", lang), myservices_empty_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data.startswith("myservices:view:"))
async def myservices_view_cb(callback: CallbackQuery, lang: str, state: FSMContext) -> None:
    """The account's action menu. Clears FSM state, so a Change Ownership
    prompt left open (by tapping Back) never swallows the next message."""
    await state.clear()
    vpn_user_id = _vpn_user_id(callback.data)
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, callback.from_user.id) if vpn_user_id else None
    if vpn_user is None:
        await _not_found(callback, lang)
        return
    trial = t("account_trial_suffix", lang) if vpn_user.is_trial else ""
    if callback.message is not None:
        await callback.message.edit_text(
            t("account_menu_heading", lang, username=vpn_user.ibsng_username, trial=trial),
            reply_markup=account_menu_keyboard(vpn_user.id, is_trial=vpn_user.is_trial, lang=lang),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("myservices:detail:"))
async def myservices_detail_cb(callback: CallbackQuery, lang: str) -> None:
    vpn_user_id = _vpn_user_id(callback.data)
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, callback.from_user.id) if vpn_user_id else None
        if vpn_user is None:
            await _not_found(callback, lang)
            return
        async with IBSngClient() as client:
            text = await build_account_info(session, client, vpn_user, lang)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user.id, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("myservices:pw:"))
async def myservices_password_start_cb(callback: CallbackQuery, lang: str) -> None:
    """Confirm first: a new password locks out every device still using
    the old one."""
    vpn_user_id = _vpn_user_id(callback.data)
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, callback.from_user.id) if vpn_user_id else None
    if vpn_user is None:
        await _not_found(callback, lang)
        return
    remaining = password_change_remaining(vpn_user)
    if remaining is not None:
        text = t("pw_cooldown", lang, days=cooldown_days_left(remaining))
        markup = back_to_account_keyboard(vpn_user.id, lang)
    else:
        text = t("pw_confirm", lang, username=vpn_user.ibsng_username)
        markup = password_confirm_keyboard(vpn_user.id, lang)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("myservices:pwdo:"))
async def myservices_password_do_cb(callback: CallbackQuery, lang: str) -> None:
    vpn_user_id = _vpn_user_id(callback.data)
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return
    try:
        async with async_session_maker() as session, IBSngClient() as client:
            result = await reset_vpn_password(
                session, client, vpn_user_id=vpn_user_id, telegram_id=callback.from_user.id
            )
    except PasswordChangeCooldownError as exc:
        text = t("pw_cooldown", lang, days=cooldown_days_left(exc.remaining))
    except ForeignGroupError:
        logger.warning("Password reset refused: account %s is not in a Homeland group", vpn_user_id)
        text = t("pw_refused_group", lang)
    except IBSngError:
        logger.exception("Password reset failed for account %s", vpn_user_id)
        text = t("pw_failed", lang)
    else:
        if result is None:
            await _not_found(callback, lang)
            return
        vpn_user, new_password = result
        text = f"{t('pw_done', lang)}\n\n{credential_lines(vpn_user.ibsng_username, new_password, lang)}"
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=back_to_account_keyboard(vpn_user_id, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("myservices:resend:"))
async def myservices_resend_cb(callback: CallbackQuery, lang: str) -> None:
    # callback_data is attacker-controlled (see the design spec's threat
    # model - ownership is checked below precisely because of this), so
    # every int() parse of a segment here is guarded: a malformed or
    # missing segment must degrade to the same not-found screen used for
    # an unowned/nonexistent service, never raise ValueError/IndexError.
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    async def _not_found() -> None:
        if callback.message is not None:
            await callback.message.edit_text(t("myservices_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()

    try:
        vpn_user_id = int(parts[2])
    except (IndexError, ValueError):
        await _not_found()
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found()
            return

        if len(parts) == 3:
            # myservices:resend:<id> - entry point, show the protocol picker.
            protocols = await list_protocols(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    t("protocol_prompt", lang), reply_markup=myservices_protocol_keyboard(protocols, vpn_user_id, lang)
                )
            await callback.answer()
            return

        if parts[3] == "protocol":
            try:
                protocol_id = int(parts[4])
            except (IndexError, ValueError):
                await _not_found()
                return

            protocol = await session.get(TutorialProtocol, protocol_id)
            if protocol is not None and protocol.label.strip().lower() == "openvpn":
                await send_openvpn_setup(callback.bot, telegram_id, session, lang=lang)
                text = t("resent_confirmation", lang)
                if callback.message is not None:
                    await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user_id, lang))
                await callback.answer()
                return

            platforms = await list_platforms(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    t("platform_prompt", lang),
                    reply_markup=myservices_platform_keyboard(platforms, vpn_user_id, protocol_id, lang),
                )
            await callback.answer()
            return

        # parts[3] == "platform": myservices:resend:<id>:platform:<protocol_id>:<platform_id>
        try:
            protocol_id = int(parts[4])
            platform_id = int(parts[5])
        except (IndexError, ValueError):
            await _not_found()
            return

        # deliver_setup does `protocol = await session.get(...)` and then
        # unconditionally accesses `protocol.label` - a syntactically valid
        # but nonexistent protocol_id would raise AttributeError there, so
        # guard the call site here (mirroring the "protocol" branch above,
        # which already does its own existence check before touching
        # `.label`) rather than calling into shared infrastructure blind.
        protocol = await session.get(TutorialProtocol, protocol_id)
        if protocol is None:
            await _not_found()
            return

        delivered, _ = await deliver_setup(
            callback.bot, telegram_id, session, protocol_id=protocol_id, platform_id=platform_id, lang=lang
        )
        text = t("resent_confirmation", lang) if delivered else t("resend_blocked", lang)
        if callback.message is not None:
            await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user_id, lang))
        await callback.answer()
