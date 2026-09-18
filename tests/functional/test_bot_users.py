from __future__ import annotations

import pytest

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_get_language_defaults_to_none() -> None:
    from app.services.bot_users import get_language, record_seen

    async with async_session_maker() as session:
        await record_seen(session, 9001, None)

    async with async_session_maker() as session:
        assert await get_language(session, 9001) is None


@pytest.mark.asyncio
async def test_set_language_round_trips() -> None:
    from app.services.bot_users import get_language, record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 9002, None)
        await set_language(session, 9002, "fa")

    async with async_session_maker() as session:
        assert await get_language(session, 9002) == "fa"


@pytest.mark.asyncio
async def test_set_language_on_unknown_telegram_id_is_a_no_op() -> None:
    from app.services.bot_users import get_language, set_language

    async with async_session_maker() as session:
        await set_language(session, 9999999, "fa")  # no BotUser row exists

    async with async_session_maker() as session:
        assert await get_language(session, 9999999) is None
