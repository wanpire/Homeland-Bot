from __future__ import annotations

import pytest

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_is_trial_enabled_defaults_true_when_unset() -> None:
    from app.services.app_config import get_config
    from app.services.trial_config import is_trial_enabled

    async with async_session_maker() as session:
        assert await get_config(session, "trial_enabled") is None
        assert await is_trial_enabled(session) is True


@pytest.mark.asyncio
async def test_set_trial_enabled_round_trips() -> None:
    from app.services.trial_config import is_trial_enabled, set_trial_enabled

    async with async_session_maker() as session:
        await set_trial_enabled(session, False)
    async with async_session_maker() as session:
        assert await is_trial_enabled(session) is False

    async with async_session_maker() as session:
        await set_trial_enabled(session, True)
    async with async_session_maker() as session:
        assert await is_trial_enabled(session) is True
