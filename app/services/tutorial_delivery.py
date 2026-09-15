# app/services/tutorial_delivery.py
from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.services.app_config import get_config
from app.services.tutorials import find_matching_profile, get_guide, is_protocol_valid_for_platform, list_platforms

_MEDIA_SENDERS = {"photo": "send_photo", "document": "send_document", "video": "send_video"}

_ANDROID_L2TP_MESSAGE = (
    "⚠️ L2TP isn't supported on Android 12 and newer (Google removed the "
    "built-in L2TP/IPsec client). Please use OpenVPN instead, or contact "
    "support for help."
)
_GUIDE_NOT_READY_MESSAGE = "📚 This guide is not ready yet — please contact support."


async def _send_media_or_text(bot: Bot, telegram_id: int, *, file_id: str | None, file_type: str | None, text: str | None, fallback_prefix: str) -> None:
    if file_id is not None and file_type is not None:
        sender = getattr(bot, _MEDIA_SENDERS.get(file_type, "send_document"))
        await sender(telegram_id, file_id, caption=text or None)
        return
    if text is not None:
        await bot.send_message(telegram_id, f"{fallback_prefix}\n\n{text}")


async def deliver_setup(
    bot: Bot, telegram_id: int, session: AsyncSession, *, protocol_id: int, platform_id: int | None,
) -> tuple[bool, int | None]:
    """Shared by the trial flow now, Buy/Renew later. Sends the OpenVPN
    profile, the tutorial guide, and any configured download link - it
    does NOT send account credentials, since not every future caller
    will want the same closing message (and the caller, not this
    function, is the one that actually has the username/password in
    scope). Returns (delivered, guide_message_id) - delivered=False
    means the caller must NOT send its own credentials message either
    (currently only the Android+L2TP compatibility gate triggers this)."""
    protocol = await session.get(TutorialProtocol, protocol_id)
    platform = await session.get(TutorialPlatform, platform_id) if platform_id is not None else None

    if platform is not None and not is_protocol_valid_for_platform(platform.label, protocol.label):
        await bot.send_message(telegram_id, _ANDROID_L2TP_MESSAGE)
        return False, None

    if protocol.label.strip().lower() == "openvpn":
        profile = await find_matching_profile(session, platform_id=platform_id)
        if profile is not None:
            await _send_media_or_text(
                bot, telegram_id, file_id=profile.file_id, file_type=profile.file_type,
                text=profile.text, fallback_prefix=f"📡 Connection profile ({profile.name})",
            )

    guide = await get_guide(session, platform_id=platform_id, protocol_id=protocol_id)
    guide_message_id: int | None = None
    if guide is not None and (guide.media_file_id is not None or guide.body_html is not None):
        if guide.media_file_id is not None and guide.media_type is not None:
            sender = getattr(bot, _MEDIA_SENDERS.get(guide.media_type, "send_document"))
            message = await sender(telegram_id, guide.media_file_id, caption=guide.body_html or None)
        else:
            message = await bot.send_message(telegram_id, guide.body_html or "")
        guide_message_id = message.message_id
    else:
        await bot.send_message(telegram_id, _GUIDE_NOT_READY_MESSAGE)

    protocol_key = protocol.label.strip().lower()
    if platform is not None:
        link = await get_config(session, f"download_link:{protocol_key}:{platform.label.strip().lower()}")
        if link:
            await bot.send_message(telegram_id, f"📥 App download link:\n{link}")
    else:
        # No platform was picked (OpenVPN's shared-guide path) - show every
        # configured platform's link at once so the user can pick their own.
        links = []
        for candidate_platform in await list_platforms(session):
            candidate_link = await get_config(session, f"download_link:{protocol_key}:{candidate_platform.label.strip().lower()}")
            if candidate_link:
                links.append(f"{candidate_platform.label}: {candidate_link}")
        if links:
            await bot.send_message(telegram_id, "📥 Download OpenVPN Connect:\n" + "\n".join(links))

    return True, guide_message_id
