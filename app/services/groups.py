from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.group import Group
from app.services.ibsng.client import IBSngClient


async def sync_groups(session: AsyncSession, client: IBSngClient) -> list[Group]:
    """Upserts every IBSng group name into the local Group cache. Safe
    to call repeatedly - existing rows just get a fresh synced_at."""
    names = await client.list_groups()
    existing = {g.name: g for g in (await session.execute(select(Group))).scalars().all()}
    now = dt.datetime.now(dt.timezone.utc)

    result: list[Group] = []
    for name in names:
        if name in existing:
            existing[name].synced_at = now
            result.append(existing[name])
        else:
            group = Group(name=name)
            session.add(group)
            result.append(group)
    await session.commit()
    return result


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.execute(select(Group).order_by(Group.name))).scalars().all())
