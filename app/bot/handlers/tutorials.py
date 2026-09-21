"""The customer-facing Tutorials section (menu:tutorials).

Protocol first, then device - the same order Trial and My Services use,
so a customer sees one consistent flow everywhere. Delivery goes through
app/services/tutorial_delivery.py's deliver_setup, the single path that
sends guides, OpenVPN profiles and download links; this handler adds no
delivery logic of its own, it only picks the (protocol, platform) pair
and closes with a keyboard so the section never dead-ends."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.bot.keyboards.tutorials import (
    tutorials_done_keyboard,
    tutorials_platform_keyboard,
    tutorials_protocol_keyboard,
)
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols

router = Router(name="tutorials")


def _is_openvpn(protocol: TutorialProtocol) -> bool:
    return protocol.label.strip().lower() == "openvpn"


@router.callback_query(F.data == "menu:tutorials")
async def tutorials_entry_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        protocols = await list_protocols(session)

    if callback.message is None:
        await callback.answer()
        return

    if not protocols:
        await show_screen(callback.message, t("tutorials_empty", lang), back_to_menu_keyboard(lang))
        await callback.answer()
        return

    # show_screen, not edit_text: an Ad Campaign button pointing here
    # arrives attached to a photo, which Telegram refuses to edit into a
    # text screen.
    await show_screen(callback.message, t("tutorials_heading", lang), tutorials_protocol_keyboard(protocols, lang))
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
        if protocol is None:
            protocols = await list_protocols(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    t("tutorials_heading", lang), reply_markup=tutorials_protocol_keyboard(protocols, lang)
                )
            await callback.answer()
            return

        # OpenVPN's guide is stored platform-independently, so asking for a
        # device would only show everyone the same page. Deliver straight
        # away with every platform's download link, exactly as the Trial
        # and My Services flows do.
        if _is_openvpn(protocol):
            await deliver_setup(
                callback.bot, callback.from_user.id, session, protocol_id=protocol_id, platform_id=None, lang=lang
            )
            await _send_done(callback, lang)
            await callback.answer()
            return

        platforms = await list_platforms(session)

    if not platforms:
        if callback.message is not None:
            await callback.message.edit_text(t("tutorials_empty", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(
            t("platform_prompt", lang), reply_markup=tutorials_platform_keyboard(platforms, protocol_id, lang)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tut:platform:"))
async def tutorials_platform_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    try:
        protocol_id, platform_id = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        await callback.answer()
        return

    async with async_session_maker() as session:
        # deliver_setup accesses protocol.label unconditionally, so a
        # syntactically valid but nonexistent id would raise there -
        # guard the call site, mirroring myservices.py.
        if await session.get(TutorialProtocol, protocol_id) is None:
            protocols = await list_protocols(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    t("tutorials_heading", lang), reply_markup=tutorials_protocol_keyboard(protocols, lang)
                )
            await callback.answer()
            return

        # delivered=False means deliver_setup already explained why (today
        # only the Android+L2TP gate), so nothing more is sent - but the
        # closing keyboard still goes out, or that explanation would be
        # the end of the road.
        await deliver_setup(
            callback.bot, callback.from_user.id, session, protocol_id=protocol_id, platform_id=platform_id, lang=lang
        )

    await _send_done(callback, lang)
    await callback.answer()


async def _send_done(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        await callback.message.answer(t("tutorials_done", lang), reply_markup=tutorials_done_keyboard(lang))
