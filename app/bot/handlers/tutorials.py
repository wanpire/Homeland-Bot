"""The customer-facing Tutorials section (menu:tutorials).

Protocol first, then device - for EVERY protocol, OpenVPN included, so
the two behave alike. The guide is sent automatically; the download link
and the OpenVPN profile are separate buttons, offered only when that
content exists, so a user takes what they need instead of receiving
three messages at once.

All sending goes through app/services/tutorial_delivery.py's senders -
this handler chooses what to offer and never formats or sends setup
material itself."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.bot.keyboards.tutorials import (
    tutorials_done_keyboard,
    tutorials_extras_keyboard,
    tutorials_platform_keyboard,
    tutorials_protocol_keyboard,
)
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.tutorial_delivery import (
    resolve_download_link,
    send_download_links,
    send_guide,
    send_profile,
)
from app.services.tutorials import (
    find_matching_profile,
    is_protocol_valid_for_platform,
    list_platforms,
    list_protocols,
)

router = Router(name="tutorials")


def _is_openvpn(protocol: TutorialProtocol) -> bool:
    return protocol.label.strip().lower() == "openvpn"


def _parse_pair(data: str) -> tuple[int, int] | None:
    parts = data.split(":")
    try:
        return int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        return None


async def _show_protocols(callback: CallbackQuery, lang: str) -> None:
    """The section's home screen, and the recovery target for any stale
    keyboard whose protocol or platform no longer exists."""
    async with async_session_maker() as session:
        protocols = await list_protocols(session)

    if callback.message is None:
        return
    if not protocols:
        await show_screen(callback.message, t("tutorials_empty", lang), back_to_menu_keyboard(lang))
        return
    # show_screen, not edit_text: an Ad Campaign button pointing here
    # arrives attached to a photo, which Telegram refuses to edit into a
    # text screen.
    await show_screen(callback.message, t("tutorials_heading", lang), tutorials_protocol_keyboard(protocols, lang))


@router.callback_query(F.data == "menu:tutorials")
async def tutorials_entry_cb(callback: CallbackQuery, lang: str) -> None:
    await _show_protocols(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("tut:protocol:"))
async def tutorials_protocol_cb(callback: CallbackQuery, lang: str) -> None:
    try:
        protocol_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)
        platforms = await list_platforms(session)

    if protocol is None:
        await _show_protocols(callback, lang)
        await callback.answer()
        return

    if not platforms:
        if callback.message is not None:
            await callback.message.edit_text(t("tutorials_empty", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return

    # Every protocol asks for a device, OpenVPN included: its guide may be
    # stored per-device, and where it isn't, send_guide falls back to the
    # generic one.
    if callback.message is not None:
        await callback.message.edit_text(
            t("platform_prompt", lang), reply_markup=tutorials_platform_keyboard(platforms, protocol_id, lang)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tut:platform:"))
async def tutorials_platform_cb(callback: CallbackQuery, lang: str) -> None:
    pair = _parse_pair(callback.data)
    if pair is None:
        await callback.answer()
        return
    protocol_id, platform_id = pair
    telegram_id = callback.from_user.id

    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)
        platform = await session.get(TutorialPlatform, platform_id)
        if protocol is None or platform is None:
            await _show_protocols(callback, lang)
            await callback.answer()
            return

        if not is_protocol_valid_for_platform(platform.label, protocol.label):
            # Android 12+ dropped its built-in L2TP client - a real OS
            # constraint. Say so and offer a way onward rather than
            # sending a guide that cannot work.
            await callback.bot.send_message(telegram_id, t("android_l2tp_unsupported", lang))
            await _send_extras_prompt(callback, lang, protocol_id, platform_id, has_link=False, has_profile=False)
            await callback.answer()
            return

        await send_guide(
            callback.bot, telegram_id, session,
            protocol_id=protocol_id, platform_id=platform_id, lang=lang, fall_back_to_generic=True,
        )
        has_link, has_profile = await _available_extras(session, protocol=protocol, platform=platform)

    await _send_extras_prompt(callback, lang, protocol_id, platform_id, has_link=has_link, has_profile=has_profile)
    await callback.answer()


@router.callback_query(F.data.startswith("tut:link:"))
async def tutorials_link_cb(callback: CallbackQuery, lang: str) -> None:
    pair = _parse_pair(callback.data)
    if pair is None:
        await callback.answer()
        return
    protocol_id, platform_id = pair

    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)
        platform = await session.get(TutorialPlatform, platform_id)
        if protocol is None or platform is None:
            await _show_protocols(callback, lang)
            await callback.answer()
            return
        sent = await send_download_links(
            callback.bot, callback.from_user.id, session, protocol=protocol, platform=platform, lang=lang
        )

    # The keyboard deliberately stays put so the user can fetch the
    # profile next; only the toast changes.
    if sent:
        await callback.answer()
    else:
        await callback.answer(t("tutorials_item_unavailable", lang), show_alert=True)


@router.callback_query(F.data.startswith("tut:profile:"))
async def tutorials_profile_cb(callback: CallbackQuery, lang: str) -> None:
    pair = _parse_pair(callback.data)
    if pair is None:
        await callback.answer()
        return
    protocol_id, platform_id = pair

    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)
        if protocol is None or not _is_openvpn(protocol):
            await _show_protocols(callback, lang)
            await callback.answer()
            return
        sent = await send_profile(callback.bot, callback.from_user.id, session, platform_id=platform_id, lang=lang)

    if sent:
        await callback.answer()
    else:
        await callback.answer(t("tutorials_item_unavailable", lang), show_alert=True)


async def _available_extras(
    session: AsyncSession, *, protocol: TutorialProtocol, platform: TutorialPlatform
) -> tuple[bool, bool]:
    """What this (protocol, device) pair actually has, so the keyboard
    only offers buttons that will deliver something."""
    has_link = await resolve_download_link(session, protocol=protocol, platform=platform) is not None
    has_profile = False
    if _is_openvpn(protocol):
        has_profile = await find_matching_profile(session, platform_id=platform.id) is not None
    return has_link, has_profile


async def _send_extras_prompt(
    callback: CallbackQuery, lang: str, protocol_id: int, platform_id: int, *, has_link: bool, has_profile: bool
) -> None:
    """The guide arrives as fresh messages, leaving the previous screen's
    keyboard scrolled far above - this is what keeps the section from
    dead-ending."""
    if callback.message is None:
        return
    if has_link or has_profile:
        await callback.message.answer(
            t("tutorials_extras_prompt", lang),
            reply_markup=tutorials_extras_keyboard(
                protocol_id, platform_id, has_link=has_link, has_profile=has_profile, lang=lang
            ),
        )
        return
    await callback.message.answer(t("tutorials_done", lang), reply_markup=tutorials_done_keyboard(lang))
