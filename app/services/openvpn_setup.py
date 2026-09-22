"""The OpenVPN setup step every account handover ends with.

Sends the .ovpn config, then asks which device the customer is on and
sends only that platform's download link once they answer. It replaced a
single message that listed all four links at once.

Deliberately looks up NO guide. None has ever been uploaded for OpenVPN,
so the lookup's honest "this guide is not ready" answer was reaching
customers in the middle of a successful purchase. Guides live in the
Tutorials section, which this step's keyboard links to.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.openvpn_setup import openvpn_platform_keyboard
from app.i18n.texts import t
from app.services.tutorial_delivery import send_profile
from app.services.tutorials import list_platforms

logger = logging.getLogger(__name__)

OPENVPN_LABEL = "OpenVPN"


async def send_openvpn_setup(bot: Bot, telegram_id: int, session: AsyncSession, *, lang: str) -> None:
    """Config file first, then the platform prompt.

    Never raises: the account is already provisioned by the time this
    runs, so a missing profile or an empty platform list must not look
    like a failed handover."""
    await send_profile(bot, telegram_id, session, platform_id=None, lang=lang)

    platforms = await list_platforms(session)
    if not platforms:
        logger.warning("OpenVPN setup: no active platforms configured, skipping the download prompt")
        return

    await bot.send_message(
        telegram_id,
        t("openvpn_pick_platform", lang),
        reply_markup=openvpn_platform_keyboard(platforms, lang),
    )
