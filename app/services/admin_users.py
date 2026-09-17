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


async def get_admin(session: AsyncSession, telegram_id: int) -> AdminUser | None:
    return (
        await session.execute(select(AdminUser).where(AdminUser.telegram_id == telegram_id))
    ).scalar_one_or_none()


async def add_admin(session: AsyncSession, telegram_id: int, level: str) -> AdminUser:
    admin = AdminUser(telegram_id=telegram_id, level=level)
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return admin


async def remove_admin(session: AsyncSession, telegram_id: int) -> None:
    admin = await get_admin(session, telegram_id)
    if admin is None:
        return
    await session.delete(admin)
    await session.commit()


async def is_last_full_admin(session: AsyncSession, telegram_id: int) -> bool:
    """True only if removing this telegram_id's DB "full" admin row would
    leave zero full-level access anywhere. A bootstrap admin from
    ADMIN_IDS always has full access regardless of DB state, so any
    configured bootstrap admin already makes this safe."""
    settings = get_settings()
    if settings.admin_id_list:
        return False
    admins = await list_admins(session)
    remaining_full = [a for a in admins if a.level == "full" and a.telegram_id != telegram_id]
    return len(remaining_full) == 0
