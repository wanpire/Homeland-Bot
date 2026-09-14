from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.app_config import AppConfig


async def get_config(session: AsyncSession, key: str) -> str | None:
    row = await session.get(AppConfig, key)
    return row.value if row is not None else None


async def set_config(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppConfig, key)
    if row is None:
        session.add(AppConfig(key=key, value=value))
    else:
        row.value = value
    await session.commit()
