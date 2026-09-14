from __future__ import annotations

import pytest

from app.db.session import async_session_maker
from app.services.ibsng.client import IBSngClient
from tests.fakes.fake_ibsng_server import FakeIBSngServer


@pytest.mark.asyncio
async def test_sync_groups_upserts_from_ibsng(ibsng_server: FakeIBSngServer) -> None:
    from app.services.groups import list_groups, sync_groups

    async with async_session_maker() as session, IBSngClient() as client:
        synced = await sync_groups(session, client)
    assert sorted(g.name for g in synced) == ["HL-1M", "HL-2M", "HL-2W", "HL-3M"]

    async with async_session_maker() as session:
        rows = await list_groups(session)
    assert sorted(g.name for g in rows) == ["HL-1M", "HL-2M", "HL-2W", "HL-3M"]


@pytest.mark.asyncio
async def test_sync_groups_is_idempotent(ibsng_server: FakeIBSngServer) -> None:
    from sqlalchemy import func, select

    from app.db.models.group import Group
    from app.services.groups import sync_groups

    async with async_session_maker() as session, IBSngClient() as client:
        await sync_groups(session, client)
    async with async_session_maker() as session, IBSngClient() as client:
        await sync_groups(session, client)

    async with async_session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(Group))).scalar_one()
    assert count == 4
