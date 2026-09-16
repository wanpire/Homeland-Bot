from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser


async def record_seen(session: AsyncSession, telegram_id: int, username: str | None) -> None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is None:
        session.add(BotUser(telegram_id=telegram_id, username=username))
    elif row.username != username:
        row.username = username
    await session.commit()


async def is_blocked(session: AsyncSession, telegram_id: int) -> bool:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    return row.is_blocked if row is not None else False


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
