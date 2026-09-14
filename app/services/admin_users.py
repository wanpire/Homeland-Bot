from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.admin_user import AdminUser

LEVELS = ("support", "sales", "full")
LEVEL_LABELS = {"support": "Support", "sales": "Sales", "full": "Full"}


async def has_level(session: AsyncSession, telegram_id: int, min_level: str) -> bool:
    """Bootstrap admins from ADMIN_IDS always have full access, matching
    every level check. Otherwise looks up the DB-managed AdminUser row
    and compares tier order."""
    settings = get_settings()
    if telegram_id in settings.admin_id_list:
        return True
    row = (
        await session.execute(select(AdminUser).where(AdminUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is None:
        return False
    return LEVELS.index(row.level) >= LEVELS.index(min_level)


async def list_admins(session: AsyncSession) -> list[AdminUser]:
    return list((await session.execute(select(AdminUser))).scalars().all())
