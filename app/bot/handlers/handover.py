"""The ho:* callbacks: the pickers of the shared handover sequence.

Every step is `ho:<source>:<ref>:<step>…` - see app/services/handover.py
for the sequence and the sources. Thin by design: parse, check the
account belongs to the tapping user, then render a picker or hand off to
`deliver_handover`."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.bot.keyboards.handover import handover_platform_keyboard, handover_protocol_keyboard
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.handover import TRIAL_SOURCE, HandoverAccount, deliver_handover, load_handover_account
from app.services.tutorials import list_platforms, list_protocols, protocols_for_platform

router = Router(name="handover")

logger = logging.getLogger(__name__)


def platform_back_callback(source: str) -> str | None:
    """The trial's device picker replaced a screen the customer navigated
    to, so it keeps a way back to the menu; a paid order's is a message
    the bot sent, where that tap would edit away the only route onward."""
    return "menu:root" if source == TRIAL_SOURCE else None


@router.callback_query(F.data.startswith("ho:"))
async def handover_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    try:
        source, ref, step = parts[1], int(parts[2]), parts[3]
        ids = [int(p) for p in parts[4:]]
    except (IndexError, ValueError):
        await callback.answer()
        return

    async with async_session_maker() as session:
        account = await load_handover_account(session, source, ref, callback.from_user.id)
        if account is None:
            await callback.answer()
            return

        if step == "back":
            platforms = await list_platforms(session)
            if callback.message is not None:
                await callback.message.edit_text(
                    t("platform_prompt", lang),
                    reply_markup=handover_platform_keyboard(
                        source, ref, platforms, lang, back_callback=platform_back_callback(source)
                    ),
                )
            await callback.answer()
            return

        if step == "os" and len(ids) == 1:
            platform = await session.get(TutorialPlatform, ids[0])
            if platform is None:
                await callback.answer()
                return
            protocols = protocols_for_platform(platform, await list_protocols(session))
            if len(protocols) != 1:
                if callback.message is not None:
                    await callback.message.edit_text(
                        t("protocol_prompt", lang),
                        reply_markup=handover_protocol_keyboard(source, ref, platform.id, protocols, lang),
                    )
                await callback.answer()
                return
            # One protocol left (Android: OpenVPN) - no choice to offer.
            protocol = protocols[0]
        elif step == "pr" and len(ids) == 2:
            platform = await session.get(TutorialPlatform, ids[0])
            protocol = await session.get(TutorialProtocol, ids[1])
            if platform is None or protocol is None:
                await callback.answer()
                return
        else:
            await callback.answer()
            return

    await run_handover(callback, account, protocol=protocol, platform=platform, lang=lang)


async def run_handover(
    callback: CallbackQuery, account: HandoverAccount, *, protocol: TutorialProtocol,
    platform: TutorialPlatform, lang: str,
) -> None:
    """Hand off to the shared sequence, disarming the tapped picker first.
    Also the entry point for the trial's legacy callbacks."""
    telegram_id = callback.from_user.id

    async def _disarm() -> bool:
        # One sequence per picker: a second tap would resend it. Two taps
        # racing each other both get here, but only one can strip the
        # keyboard - Telegram refuses the other as "not modified".
        if callback.message is None:
            return True
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return False
            logger.warning("Could not disarm the handover picker for %s: %s", telegram_id, exc)
        return True

    await deliver_handover(
        callback.bot, telegram_id, account, protocol=protocol, platform=platform, lang=lang, claim=_disarm,
        anchor_message_id=callback.message.message_id if callback.message is not None else None,
    )
    await callback.answer()
