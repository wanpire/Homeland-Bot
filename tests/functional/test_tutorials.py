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
