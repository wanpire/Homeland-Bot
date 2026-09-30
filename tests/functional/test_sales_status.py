"""The sales switch and the paused message, below the handlers."""

from __future__ import annotations

import pytest

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_sales_are_enabled_by_default() -> None:
    from app.services.sales_status import are_sales_enabled

    async with async_session_maker() as session:
        assert await are_sales_enabled(session) is True


@pytest.mark.asyncio
async def test_disabling_persists_across_fresh_sessions() -> None:
    """A bot restart reads the flag from the DB, which is exactly what a
    fresh session does."""
    from app.services.app_config import get_config
    from app.services.sales_status import are_sales_enabled, set_sales_enabled

    async with async_session_maker() as session:
        await set_sales_enabled(session, False)
    async with async_session_maker() as session:
        assert await are_sales_enabled(session) is False
        assert await get_config(session, "sales_enabled") == "false"

    async with async_session_maker() as session:
        await set_sales_enabled(session, True)
    async with async_session_maker() as session:
        assert await are_sales_enabled(session) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lang", "fragment"),
    [("en", "Sales are temporarily paused"), ("fa", "فروش موقتاً متوقف شده است")],
)
async def test_default_message_when_nothing_is_set(lang: str, fragment: str) -> None:
    from app.services.sales_status import get_custom_paused_message, sales_paused_text

    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, lang) is None
        assert fragment in await sales_paused_text(session, lang)


@pytest.mark.asyncio
async def test_custom_message_is_per_language() -> None:
    from app.services.sales_status import sales_paused_text, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "فروش بسته است")
    async with async_session_maker() as session:
        assert await sales_paused_text(session, "fa") == "فروش بسته است"
        # English was not set, so it still falls back to its default.
        assert "Sales are temporarily paused" in await sales_paused_text(session, "en")


@pytest.mark.asyncio
async def test_custom_message_is_html_escaped() -> None:
    from app.services.sales_status import sales_paused_text, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "en", "Back <soon> & better")
        assert await sales_paused_text(session, "en") == "Back &lt;soon&gt; &amp; better"


@pytest.mark.asyncio
async def test_unknown_language_reads_the_english_message() -> None:
    from app.services.sales_status import sales_paused_text, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "en", "Closed")
        assert await sales_paused_text(session, "de") == "Closed"


@pytest.mark.asyncio
async def test_clearing_restores_both_defaults() -> None:
    from app.services.sales_status import (
        clear_custom_paused_messages,
        get_custom_paused_message,
        set_custom_paused_message,
    )

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "الف")
        await set_custom_paused_message(session, "en", "A")
        await clear_custom_paused_messages(session)
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "fa") is None
        assert await get_custom_paused_message(session, "en") is None


@pytest.mark.asyncio
async def test_setting_an_unsupported_language_is_refused() -> None:
    from app.services.sales_status import set_custom_paused_message

    async with async_session_maker() as session:
        with pytest.raises(ValueError):
            await set_custom_paused_message(session, "de", "Geschlossen")
