from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser


async def record_seen(session: AsyncSession, telegram_id: int, username: str | None) -> bool:
    """Returns True when this call created the row, i.e. a genuinely new
    user. The operational log needs that distinction: it fires on every
    update, and "new user" must mean the first one, not each one."""
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    created = row is None
    if row is None:
        session.add(BotUser(telegram_id=telegram_id, username=username))
    elif row.username != username:
        row.username = username
    await session.commit()
    return created


async def is_blocked(session: AsyncSession, telegram_id: int) -> bool:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    return row.is_blocked if row is not None else False


async def bot_user_exists(session: AsyncSession, telegram_id: int) -> bool:
    result = await session.execute(select(BotUser.id).where(BotUser.telegram_id == telegram_id).limit(1))
    return result.scalar_one_or_none() is not None


async def list_blocked_users(session: AsyncSession) -> list[BotUser]:
    result = await session.execute(select(BotUser).where(BotUser.is_blocked.is_(True)).order_by(BotUser.id))
    return list(result.scalars().all())


async def block_user(session: AsyncSession, telegram_id: int, blocked: bool = True) -> None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is not None:
        row.is_blocked = blocked
        await session.commit()


async def list_bot_user_ids(session: AsyncSession) -> list[int]:
    return [row[0] for row in (await session.execute(select(BotUser.telegram_id))).all()]


async def get_language(session: AsyncSession, telegram_id: int) -> str | None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    return row.language if row is not None else None


async def set_language(session: AsyncSession, telegram_id: int, language: str) -> None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is not None:
        row.language = language
        await session.commit()
