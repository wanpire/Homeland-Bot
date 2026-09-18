from __future__ import annotations

import pytest

from app.db.session import async_session_maker
from app.services.ibsng.client import IBSngClient
from tests.fakes.fake_ibsng_server import FakeIBSngServer

_HOMELAND_GROUP_NAMES = [
    "1M-1U-Iran-10G",
    "1M-1U-Iran-30G",
    "1M-1U-Iran-Unlimited",
    "2M-1U-Iran-20G",
    "2M-1U-Iran-60G",
    "2M-1U-Iran-Unlimited",
    "2W-1U-Iran-5G",
    "3M-1U-Iran-100G",
    "3M-1U-Iran-30G",
    "3M-1U-Iran-Unlimited",
    "Trial-Iran",
]

# The fake IBSng server (tests/fakes/fake_ibsng_server.py) also lists a
# sample of AloBot's own groups, on the same shared instance - sync_groups
# must never upsert any of these (spec §14).
_ALOBOT_GROUP_NAMES = ["1M-1U", "1M-2U", "1M-1U-Prime", "Trial"]


@pytest.mark.asyncio
async def test_sync_groups_upserts_only_homeland_groups(ibsng_server: FakeIBSngServer) -> None:
    from app.services.groups import list_groups, sync_groups

    async with async_session_maker() as session, IBSngClient() as client:
        synced = await sync_groups(session, client)
    assert sorted(g.name for g in synced) == _HOMELAND_GROUP_NAMES

    async with async_session_maker() as session:
        rows = await list_groups(session)
    assert sorted(g.name for g in rows) == _HOMELAND_GROUP_NAMES


@pytest.mark.asyncio
async def test_sync_groups_excludes_alobot_groups(ibsng_server: FakeIBSngServer) -> None:
    """The fake server's list_groups() includes AloBot-style names
    (confirmed present - see fake_ibsng_server.py's group list, which
    mirrors the real shared instance). None of them may ever reach the
    local Group table."""
    from app.services.groups import list_groups, sync_groups

    async with async_session_maker() as session, IBSngClient() as client:
        real_names = await client.list_groups()
        await sync_groups(session, client)

    assert set(_ALOBOT_GROUP_NAMES).issubset(real_names), (
        "test fixture drifted - the fake server must still list AloBot-style "
        "groups for this test to actually prove the filter works"
    )

    async with async_session_maker() as session:
        rows = await list_groups(session)
    synced_names = {g.name for g in rows}
    assert synced_names.isdisjoint(_ALOBOT_GROUP_NAMES)


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
    assert count == len(_HOMELAND_GROUP_NAMES)
