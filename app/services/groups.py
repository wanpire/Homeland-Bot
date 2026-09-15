from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.group import Group
from app.services.ibsng.client import IBSngClient

# Homeland shares one IBSng instance with AloBot, a separate Telegram bot
# project with its own groups (Normal/Prime/Junior tiers). list_groups()
# below returns every group on the shared instance, AloBot's included -
# this allowlist is the ONLY thing standing between that and Homeland
# accidentally syncing/referencing a group that isn't its own. Every real
# Homeland group name matches this pattern (spec §14, confirmed against
# the 7 real IBSng groups); no AloBot group name does. Any future code
# that calls IBSngClient.list_groups() directly, bypassing sync_groups,
# must apply the same filter before presenting options to anyone.
_ALLOWED_GROUP_PREFIXES = ("2W-", "1M-", "2M-", "3M-", "Trial-")


def _is_homeland_group(name: str) -> bool:
    return name.startswith(_ALLOWED_GROUP_PREFIXES) and "Iran" in name


async def sync_groups(session: AsyncSession, client: IBSngClient) -> list[Group]:
    """Upserts every Homeland-namespaced IBSng group name into the local
    Group cache - see _is_homeland_group's module-level comment. Groups
    outside that namespace (AloBot's, on the same shared instance) are
    silently skipped, never upserted, never returned. Safe to call
    repeatedly - existing rows just get a fresh synced_at."""
    names = [name for name in await client.list_groups() if _is_homeland_group(name)]
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
