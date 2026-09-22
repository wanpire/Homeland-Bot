# app/services/tutorial_delivery.py
"""The ONE place that sends setup material to a customer.

Split into three senders - profile, guide, download links - because the
Tutorials section offers them as separate buttons while Trial and My
Services send all three at once. `deliver_setup` composes the same three
in the same order it always did, so those two flows are unchanged. Never
add a fourth path that sends this material; add a sender here instead.
"""

from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.i18n.texts import t
from app.services.app_config import get_config
from app.services.tutorials import find_matching_profile, get_guide, is_protocol_valid_for_platform, list_platforms

_MEDIA_SENDERS = {"photo": "send_photo", "document": "send_document", "video": "send_video"}

#: Platform segment of a download-link AppConfig key for a link that
#: applies to every platform ("Generic (any platform)" in the admin flow).
GENERIC_PLATFORM_KEY = "any"


def download_link_key(*, protocol_label: str, platform_label: str | None) -> str:
    """The one place the `download_link:{protocol}:{platform}` AppConfig
    key format is spelled out - the admin flow writes through it and the
    senders below read through it, so the two can't drift (they already
    did once: the admin's generic `:any` key was written but never read)."""
    platform_key = platform_label.strip().lower() if platform_label is not None else GENERIC_PLATFORM_KEY
    return f"download_link:{protocol_label.strip().lower()}:{platform_key}"


async def _send_media_or_text(
    bot: Bot, telegram_id: int, *, file_id: str | None, file_type: str | None, text: str | None, fallback_prefix: str
) -> None:
    if file_id is not None and file_type is not None:
        sender = getattr(bot, _MEDIA_SENDERS.get(file_type, "send_document"))
        await sender(telegram_id, file_id, caption=text or None)
        return
    if text is not None:
        await bot.send_message(telegram_id, f"{fallback_prefix}\n\n{text}")


async def resolve_download_link(
    session: AsyncSession, *, protocol: TutorialProtocol, platform: TutorialPlatform | None
) -> str | None:
    """A platform-specific link wins over the admin's "Generic (any
    platform)" one. Returns None when neither is configured, which is how
    the Tutorials keyboard decides whether to offer the button at all."""
    generic = await get_config(session, download_link_key(protocol_label=protocol.label, platform_label=None))
    if platform is None:
        return generic
    specific = await get_config(
        session, download_link_key(protocol_label=protocol.label, platform_label=platform.label)
    )
    return specific or generic


async def send_profile(bot: Bot, telegram_id: int, session: AsyncSession, *, platform_id: int | None, lang: str) -> bool:
    """The OpenVPN connection profile. Returns False when none is
    configured, so a caller can avoid promising one."""
    profile = await find_matching_profile(session, platform_id=platform_id)
    if profile is None:
        return False
    await _send_media_or_text(
        bot, telegram_id, file_id=profile.file_id, file_type=profile.file_type,
        text=profile.text, fallback_prefix=t("connection_profile_prefix", lang, name=profile.name),
    )
    return True


async def send_guide(
    bot: Bot, telegram_id: int, session: AsyncSession, *, protocol_id: int, platform_id: int | None,
    lang: str, fall_back_to_generic: bool = False, notify_if_missing: bool = True,
) -> int | None:
    """The tutorial itself. Returns the sent message id, or None when
    nothing was configured (in which case the "not ready" note is sent).

    `fall_back_to_generic` is for the Tutorials section, which asks for a
    device even on OpenVPN: an admin may have uploaded one generic
    OpenVPN guide rather than four identical per-device copies, and that
    generic guide must still reach the user. Off by default so Trial and
    My Services keep their exact current lookup."""
    guide = await get_guide(session, platform_id=platform_id, protocol_id=protocol_id)
    if guide is None and fall_back_to_generic and platform_id is not None:
        guide = await get_guide(session, platform_id=None, protocol_id=protocol_id)

    if guide is None or (guide.media_file_id is None and guide.body_html is None):
        # A delivery flow passes notify_if_missing=False: it has just
        # handed over working credentials and must not apologise for a
        # guide the customer never asked for. Tutorials keeps the
        # default, where "not ready" answers an explicit request.
        if notify_if_missing:
            await bot.send_message(telegram_id, t("guide_not_ready", lang))
        return None

    if guide.media_file_id is not None and guide.media_type is not None:
        sender = getattr(bot, _MEDIA_SENDERS.get(guide.media_type, "send_document"))
        message = await sender(telegram_id, guide.media_file_id, caption=guide.body_html or None)
    else:
        message = await bot.send_message(telegram_id, guide.body_html or "")
    return message.message_id


async def send_download_links(
    bot: Bot, telegram_id: int, session: AsyncSession, *, protocol: TutorialProtocol,
    platform: TutorialPlatform | None, lang: str,
) -> bool:
    """One link for a chosen platform, or every platform's link at once
    when no platform was chosen (OpenVPN's shared-guide path, where the
    user picks their own). Returns False when nothing is configured."""
    if platform is not None:
        link = await resolve_download_link(session, protocol=protocol, platform=platform)
        if not link:
            return False
        await bot.send_message(telegram_id, f"{t('download_link_prefix', lang)}\n{link}")
        return True

    links = []
    for candidate in await list_platforms(session):
        candidate_link = await get_config(
            session, download_link_key(protocol_label=protocol.label, platform_label=candidate.label)
        )
        if candidate_link:
            links.append(f"{candidate.label}: {candidate_link}")
    generic = await get_config(session, download_link_key(protocol_label=protocol.label, platform_label=None))
    if generic:
        links.append(f"{t('any_platform_label', lang)} {generic}")
    if not links:
        return False
    await bot.send_message(telegram_id, t("download_openvpn_links_heading", lang) + "\n" + "\n".join(links))
    return True


async def deliver_setup(
    bot: Bot, telegram_id: int, session: AsyncSession, *, protocol_id: int, platform_id: int | None, lang: str = "en",
) -> tuple[bool, int | None]:
    """Profile, guide and download link in one go - what the Trial and My
    Services flows send after provisioning. It does NOT send account
    credentials, since not every caller wants the same closing message
    (and the caller, not this function, holds the username/password).
    Returns (delivered, guide_message_id); delivered=False means the
    caller must NOT send its own credentials message either (currently
    only the Android+L2TP compatibility gate triggers this).

    `lang` defaults to "en" so a not-yet-migrated caller keeps working
    correctly until it starts passing lang explicitly."""
    protocol = await session.get(TutorialProtocol, protocol_id)
    platform = await session.get(TutorialPlatform, platform_id) if platform_id is not None else None

    if platform is not None and not is_protocol_valid_for_platform(platform.label, protocol.label):
        await bot.send_message(telegram_id, t("android_l2tp_unsupported", lang))
        return False, None

    if protocol.label.strip().lower() == "openvpn":
        await send_profile(bot, telegram_id, session, platform_id=platform_id, lang=lang)

    guide_message_id = await send_guide(
        bot, telegram_id, session, protocol_id=protocol_id, platform_id=platform_id, lang=lang,
        notify_if_missing=False,
    )
    await send_download_links(bot, telegram_id, session, protocol=protocol, platform=platform, lang=lang)
    return True, guide_message_id
