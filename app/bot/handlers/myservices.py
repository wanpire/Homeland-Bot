from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.myservices import (
    myservices_detail_keyboard,
    myservices_empty_keyboard,
    myservices_list_keyboard,
    myservices_platform_keyboard,
    myservices_protocol_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import get_plan, plan_display_name
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import get_owned_vpn_user, get_service_status, list_services_with_status

router = Router(name="myservices")


@router.callback_query(F.data == "menu:myservices")
async def myservices_list_cb(callback: CallbackQuery, lang: str) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session, IBSngClient() as client:
        rows = await list_services_with_status(session, client, telegram_id)

    if not rows:
        if callback.message is not None:
            await callback.message.edit_text(t("myservices_empty", lang), reply_markup=myservices_empty_keyboard(lang))
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(t("myservices_heading", lang), reply_markup=myservices_list_keyboard(rows, lang))
    await callback.answer()


async def _detail_text(session: AsyncSession, client: IBSngClient, vpn_user: VPNUser, lang: str) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    name = plan_display_name(plan, lang) if plan is not None else vpn_user.ibsng_group
    status, expiry = await get_service_status(client, vpn_user.ibsng_username)

    if status == "active":
        status_line = t("status_line_active", lang, date=f"{expiry:%Y-%m-%d %H:%M}")
    elif status == "expired":
        status_line = t("status_line_expired", lang, date=f"{expiry:%Y-%m-%d %H:%M}")
    elif status == "pending":
        status_line = t("status_line_pending", lang)
    else:
        status_line = t("status_line_unknown", lang)

    # Mirrors app/bot/handlers/trial.py's _send_trial_credentials: a
    # transient IBSng failure fetching the password must never crash the
    # screen showing it - get_service_status above is already immune to
    # this (it never raises), but get_user_password has no such
    # guarantee, so it needs its own try/except here.
    try:
        password = await client.get_user_password(username=vpn_user.ibsng_username)
    except IBSngError:
        password = None
    password_line = (
        f"{t('password_label', lang)}: <code>{password}</code>"
        if password is not None
        else t("password_unavailable", lang)
    )

    return (
        f"🔑 <b>{name}</b>\n"
        f"{status_line}\n\n"
        f"{t('username_label', lang)}: <code>{vpn_user.ibsng_username}</code>\n"
        f"{password_line}"
    )


@router.callback_query(F.data.startswith("myservices:view:"))
async def myservices_view_cb(callback: CallbackQuery, lang: str) -> None:
    vpn_user_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            if callback.message is not None:
                await callback.message.edit_text(t("myservices_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        async with IBSngClient() as client:
            text = await _detail_text(session, client, vpn_user, lang)

    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=myservices_detail_keyboard(vpn_user.id, lang))
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
                delivered, _ = await deliver_setup(
                    callback.bot, telegram_id, session, protocol_id=protocol_id, platform_id=None, lang=lang
                )
                text = t("resent_confirmation", lang) if delivered else t("resend_blocked", lang)
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
