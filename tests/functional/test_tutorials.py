from __future__ import annotations

import pytest

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_seed_migration_creates_four_platforms() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_platform import TutorialPlatform

    async with async_session_maker() as session:
        rows = (await session.execute(select(TutorialPlatform).order_by(TutorialPlatform.sort_order))).scalars().all()

    assert [p.label for p in rows] == ["iOS", "Android", "Windows", "macOS"]
    assert all(p.is_active for p in rows)


@pytest.mark.asyncio
async def test_seed_migration_creates_two_protocols() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        rows = (await session.execute(select(TutorialProtocol).order_by(TutorialProtocol.sort_order))).scalars().all()

    assert [p.label for p in rows] == ["L2TP", "OpenVPN"]


@pytest.mark.asyncio
async def test_tutorial_guide_allows_one_null_platform_row_per_protocol() -> None:
    """The OpenVPN guide has platform_id=NULL (shared across platforms) -
    the partial unique index must still stop a SECOND null-platform row
    for the same protocol from being inserted."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import select

    from app.db.models.tutorial_guide import TutorialGuide
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        openvpn = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one()
        session.add(TutorialGuide(platform_id=None, protocol_id=openvpn.id, is_active=True))
        await session.commit()

    async with async_session_maker() as session:
        openvpn = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one()
        session.add(TutorialGuide(platform_id=None, protocol_id=openvpn.id, is_active=True))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_tutorial_guide_allows_one_row_per_platform_protocol_pair() -> None:
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import select

    from app.db.models.tutorial_guide import TutorialGuide
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        ios = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one()
        l2tp = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one()
        session.add(TutorialGuide(platform_id=ios.id, protocol_id=l2tp.id, is_active=True))
        await session.commit()
        ios_id, l2tp_id = ios.id, l2tp.id

    async with async_session_maker() as session:
        session.add(TutorialGuide(platform_id=ios_id, protocol_id=l2tp_id, is_active=True))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_is_protocol_valid_for_platform_blocks_android_l2tp() -> None:
    from app.services.tutorials import is_protocol_valid_for_platform

    assert is_protocol_valid_for_platform("Android", "L2TP") is False
    assert is_protocol_valid_for_platform("iOS", "L2TP") is True
    assert is_protocol_valid_for_platform("Android", "OpenVPN") is True


@pytest.mark.asyncio
async def test_upsert_guide_creates_then_updates() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_guide import TutorialGuide
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorials import get_guide, upsert_guide

    async with async_session_maker() as session:
        ios = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one()
        l2tp = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one()
        ios_id, l2tp_id = ios.id, l2tp.id
        created = await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id="file-1", media_type="photo")

    assert created.media_file_id == "file-1"

    async with async_session_maker() as session:
        updated = await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id="file-2", media_type="document")

    assert updated.id == created.id
    assert updated.media_file_id == "file-2"
    assert updated.media_type == "document"

    async with async_session_maker() as session:
        count = (await session.execute(select(TutorialGuide))).scalars().all()
    assert len(count) == 1


@pytest.mark.asyncio
async def test_get_guide_returns_none_when_not_configured() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorials import get_guide

    async with async_session_maker() as session:
        openvpn = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one()
        guide = await get_guide(session, platform_id=None, protocol_id=openvpn.id)

    assert guide is None


@pytest.mark.asyncio
async def test_find_matching_profile_prefers_platform_specific_over_generic() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.services.tutorials import find_matching_profile, upsert_profile

    async with async_session_maker() as session:
        ios = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one()
        ios_id = ios.id
        await upsert_profile(session, platform_id=None, name="Generic", file_id="generic-file", file_type="document", text=None)
        await upsert_profile(session, platform_id=ios_id, name="iOS-specific", file_id="ios-file", file_type="document", text=None)

    async with async_session_maker() as session:
        matched = await find_matching_profile(session, platform_id=ios_id)
    assert matched is not None
    assert matched.name == "iOS-specific"

    async with async_session_maker() as session:
        android_id = (
            await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "Android"))
        ).scalar_one().id
        fallback = await find_matching_profile(session, platform_id=android_id)
    assert fallback is not None
    assert fallback.name == "Generic"
