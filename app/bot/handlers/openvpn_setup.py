"""The ovpn:* callbacks behind the post-handover platform picker."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.openvpn_setup import OPENVPN_LABEL
from app.services.tutorial_delivery import send_download_links

logger = logging.getLogger(__name__)

router = Router(name="openvpn_setup")


@router.callback_query(F.data.startswith("ovpn:link:"))
async def openvpn_link_cb(callback: CallbackQuery, lang: str) -> None:
    try:
        platform_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    async with async_session_maker() as session:
        platform = await session.get(TutorialPlatform, platform_id)
        protocol = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == OPENVPN_LABEL))
        ).scalar_one_or_none()
        if platform is None or protocol is None:
            await callback.answer()
            return
        sent = await send_download_links(
            callback.bot, callback.from_user.id, session, protocol=protocol, platform=platform, lang=lang
        )

    # The keyboard deliberately stays put so a customer with two devices
    # can take both links; only the toast differs.
    if sent:
        await callback.answer()
    else:
        await callback.answer(t("openvpn_link_unavailable", lang), show_alert=True)
