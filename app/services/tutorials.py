# app/services/tutorials.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.openvpn_profile import OpenVpnProfile
from app.db.models.tutorial_guide import TutorialGuide
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol


async def list_platforms(session: AsyncSession, *, active_only: bool = True) -> list[TutorialPlatform]:
    query = select(TutorialPlatform).order_by(TutorialPlatform.sort_order, TutorialPlatform.id)
    if active_only:
        query = query.where(TutorialPlatform.is_active.is_(True))
    return list((await session.execute(query)).scalars().all())


async def list_protocols(session: AsyncSession, *, active_only: bool = True) -> list[TutorialProtocol]:
    query = select(TutorialProtocol).order_by(TutorialProtocol.sort_order, TutorialProtocol.id)
    if active_only:
        query = query.where(TutorialProtocol.is_active.is_(True))
    return list((await session.execute(query)).scalars().all())


async def get_guide(session: AsyncSession, *, platform_id: int | None, protocol_id: int) -> TutorialGuide | None:
    query = select(TutorialGuide).where(
        TutorialGuide.protocol_id == protocol_id,
        TutorialGuide.is_active.is_(True),
    )
    query = query.where(TutorialGuide.platform_id.is_(None) if platform_id is None else TutorialGuide.platform_id == platform_id)
    return (await session.execute(query)).scalar_one_or_none()


async def upsert_guide(
    session: AsyncSession, *, platform_id: int | None, protocol_id: int,
    media_file_id: str | None, media_type: str | None,
) -> TutorialGuide:
    guide = await get_guide(session, platform_id=platform_id, protocol_id=protocol_id)
    if guide is None:
        guide = TutorialGuide(platform_id=platform_id, protocol_id=protocol_id)
        session.add(guide)
    guide.media_file_id = media_file_id
    guide.media_type = media_type
    await session.commit()
    await session.refresh(guide)
    return guide


async def find_matching_profile(session: AsyncSession, *, platform_id: int | None) -> OpenVpnProfile | None:
    """A platform-specific active profile wins over the generic
    (platform_id=NULL) one, if both exist. Ported from AloBot's
    find_matching_profile, minus the category/location dimension
    Homeland doesn't have.

    Newest-first ordering matters: upsert_profile always INSERTs a new
    row, so re-uploading a corrected file leaves two active rows for the
    same match. Without an explicit ORDER BY, which one users get is
    whatever order Postgres happens to return - here the most recent
    upload always wins, which is what an admin re-uploading expects."""
    result = await session.execute(
        select(OpenVpnProfile)
        .where(OpenVpnProfile.is_active.is_(True))
        .order_by(OpenVpnProfile.created_at.desc(), OpenVpnProfile.id.desc())
    )
    candidates = list(result.scalars().all())
    if not candidates:
        return None
    specific = next((p for p in candidates if p.platform_id == platform_id and platform_id is not None), None)
    if specific is not None:
        return specific
    return next((p for p in candidates if p.platform_id is None), None)


async def upsert_profile(
    session: AsyncSession, *, platform_id: int | None, name: str,
    file_id: str | None, file_type: str | None, text: str | None,
) -> OpenVpnProfile:
    profile = OpenVpnProfile(platform_id=platform_id, name=name, file_id=file_id, file_type=file_type, text=text)
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


def is_protocol_valid_for_platform(platform_label: str, protocol_label: str) -> bool:
    """Android 12+ dropped its built-in L2TP/IPsec client - a real OS
    constraint, not a Homeland business rule. Ported from AloBot's
    is_protocol_valid_for_platform."""
    is_android = platform_label.strip().lower() == "android"
    is_l2tp = protocol_label.strip().lower() == "l2tp"
    return not (is_android and is_l2tp)


def protocols_for_platform(platform: TutorialPlatform, protocols: list[TutorialProtocol]) -> list[TutorialProtocol]:
    """The protocols a device can actually use, in the given order. The
    handover sequence builds its protocol picker from this and skips the
    picker when exactly one is left (Android: OpenVPN only), so any flow
    that reuses the sequence inherits the rule rather than re-checking it."""
    return [p for p in protocols if is_protocol_valid_for_platform(platform.label, p.label)]
