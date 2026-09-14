from __future__ import annotations

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID


@pytest.mark.asyncio
async def test_env_admin_has_full_level_without_a_db_row() -> None:
    from app.services.admin_users import has_level

    async with async_session_maker() as session:
        assert await has_level(session, FAKE_ADMIN_ID, "full") is True


@pytest.mark.asyncio
async def test_unknown_user_has_no_level() -> None:
    from app.services.admin_users import has_level

    async with async_session_maker() as session:
        assert await has_level(session, 999, "support") is False


@pytest.mark.asyncio
async def test_db_admin_level_ordering() -> None:
    from app.db.models.admin_user import AdminUser
    from app.services.admin_users import has_level

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=42, level="sales"))
        await session.commit()

    async with async_session_maker() as session:
        assert await has_level(session, 42, "support") is True
        assert await has_level(session, 42, "sales") is True
        assert await has_level(session, 42, "full") is False


@pytest.mark.asyncio
async def test_record_seen_creates_then_updates_username() -> None:
    from sqlalchemy import select

    from app.db.models.bot_user import BotUser
    from app.services.bot_users import record_seen

    async with async_session_maker() as session:
        await record_seen(session, 77, "first_name")
    async with async_session_maker() as session:
        await record_seen(session, 77, "changed_name")

    async with async_session_maker() as session:
        row = (await session.execute(select(BotUser).where(BotUser.telegram_id == 77))).scalar_one()
        assert row.username == "changed_name"


@pytest.mark.asyncio
async def test_block_and_unblock_user() -> None:
    from app.services.bot_users import block_user, is_blocked, record_seen

    async with async_session_maker() as session:
        await record_seen(session, 88, "target")

    async with async_session_maker() as session:
        assert await is_blocked(session, 88) is False
        await block_user(session, 88, blocked=True)

    async with async_session_maker() as session:
        assert await is_blocked(session, 88) is True
        await block_user(session, 88, blocked=False)

    async with async_session_maker() as session:
        assert await is_blocked(session, 88) is False


@pytest.mark.asyncio
async def test_app_config_get_set_roundtrip() -> None:
    from app.services.app_config import get_config, set_config

    async with async_session_maker() as session:
        assert await get_config(session, "support_username") is None
        await set_config(session, "support_username", "@homeland_support")

    async with async_session_maker() as session:
        assert await get_config(session, "support_username") == "@homeland_support"
