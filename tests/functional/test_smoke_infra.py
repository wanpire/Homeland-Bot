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
