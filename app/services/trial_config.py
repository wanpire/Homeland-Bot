from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_config import get_config, set_config

_ENABLED_KEY = "trial_enabled"


async def is_trial_enabled(session: AsyncSession) -> bool:
    """Unset config (never configured) reads as enabled - trials are an
    opt-out feature, matching how reminder_enabled treats a missing value
    as the enabled default."""
    return (await get_config(session, _ENABLED_KEY)) != "false"


async def set_trial_enabled(session: AsyncSession, enabled: bool) -> None:
    await set_config(session, _ENABLED_KEY, "true" if enabled else "false")
