from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import seed_bot_user
from tests.fakes.fake_ibsng_server import FakeIBSngServer


@pytest.mark.asyncio
async def test_database_is_reachable_and_seedable() -> None:
    from app.db.models.bot_user import BotUser

    async with async_session_maker() as session:
        await seed_bot_user(session, 555, username="alice")

    async with async_session_maker() as session:
        row = (await session.execute(select(BotUser).where(BotUser.telegram_id == 555))).scalar_one()
        assert row.username == "alice"


@pytest.mark.asyncio
async def test_database_truncates_between_tests() -> None:
    """Depends on running after the seeding test above in file order -
    proves _clean_database actually truncates, not just that seeding
    works."""
    from app.db.models.bot_user import BotUser

    async with async_session_maker() as session:
        rows = (await session.execute(select(BotUser))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cache_key", "table", "identity_column"),
    [
        ("groups", "groups", "name"),
        ("plans", "plans", "name"),
        ("platforms", "tutorial_platforms", "label"),
        ("protocols", "tutorial_protocols", "label"),
    ],
)
async def test_seeded_catalog_ids_match_the_live_rows_after_a_reseed(
    seeded_catalog: dict, cache_key: str, table: str, identity_column: str
) -> None:
    """seeded_catalog caches the ids ONCE, right after the migrations run,
    but _clean_database TRUNCATE ... RESTART IDENTITYs and re-inserts the
    catalog before every single test. If the re-seed lets the sequence
    reassign ids, every cached id silently points at the wrong row (or at
    no row at all) - which is exactly what happened: the plan ids the
    migrations assigned are 5-11 (revision 0004 deletes 0002's four
    placeholders first), while an unpinned re-seed renumbers them 1-7.

    This asserts the id->identity mapping the cache promises, rather than
    comparing a re-fetch against itself."""
    from sqlalchemy import text

    async with async_session_maker() as session:
        live = {
            row[0]: row[1]
            for row in (await session.execute(text(f"SELECT id, {identity_column} FROM {table}"))).all()
        }

    cached = {row["id"]: row[identity_column] for row in seeded_catalog[cache_key]}
    assert cached, f"seeded_catalog[{cache_key!r}] is empty - nothing was verified"
    assert live == cached


@pytest.mark.asyncio
async def test_new_row_in_a_reseeded_table_does_not_collide_with_a_pinned_id() -> None:
    """The re-seed pins ids explicitly, so the identity sequence must be
    bumped past them - otherwise the first DB-assigned insert into one of
    these tables collides with a seed row's primary key."""
    from app.db.models.group import Group

    async with async_session_maker() as session:
        group = Group(name="3M-1U-Iran-999G")
        session.add(group)
        await session.commit()
        assert group.id is not None

    async with async_session_maker() as session:
        names = (await session.execute(select(Group.name))).scalars().all()
        assert "3M-1U-Iran-999G" in names


@pytest.mark.asyncio
async def test_redis_is_reachable() -> None:
    from app.redis import get_redis

    client = get_redis()
    await client.set("smoke", "ok")
    assert await client.get("smoke") == "ok"
    await client.aclose()


def test_fake_ibsng_server_responds(ibsng_server: FakeIBSngServer) -> None:
    import xmlrpc.client

    proxy = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{ibsng_server.port}")
    groups = proxy.group.listGroups({})
    assert "2W-1U-Iran-5G" in groups
    assert "Trial-Iran" in groups
