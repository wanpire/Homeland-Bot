from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_config import get_config, set_config

_USERNAMES_KEY = "mandatory_channel_usernames"
_ENABLED_KEY = "mandatory_channel_enabled"


async def get_mandatory_channels(session: AsyncSession) -> list[str]:
    """Returns the configured channel usernames (no leading @), or an
    empty list if none are set."""
    raw = await get_config(session, _USERNAMES_KEY)
    if not raw:
        return []
    return [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]


async def set_mandatory_channels(session: AsyncSession, usernames: list[str]) -> None:
    await set_config(session, _USERNAMES_KEY, ",".join(u.strip().lstrip("@") for u in usernames if u.strip()))


async def is_mandatory_channel_enabled(session: AsyncSession) -> bool:
    return (await get_config(session, _ENABLED_KEY)) == "true"


async def set_mandatory_channel_enabled(session: AsyncSession, enabled: bool) -> None:
    await set_config(session, _ENABLED_KEY, "true" if enabled else "false")
