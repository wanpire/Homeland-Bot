from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.plan import Plan


async def list_plans(session: AsyncSession, *, active_only: bool = True) -> list[Plan]:
    query = select(Plan).order_by(Plan.sort_order, Plan.id)
    if active_only:
        query = query.where(Plan.is_active.is_(True))
    return list((await session.execute(query)).scalars().all())


async def get_plan(session: AsyncSession, plan_id: int) -> Plan | None:
    return await session.get(Plan, plan_id)


async def update_plan(
    session: AsyncSession,
    plan_id: int,
    *,
    price_usd: Decimal | None = None,
    group_name: str | None = None,
    is_active: bool | None = None,
) -> Plan | None:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        return None
    if price_usd is not None:
        plan.price_usd = price_usd
    if group_name is not None:
        plan.group_name = group_name
    if is_active is not None:
        plan.is_active = is_active
    await session.commit()
    await session.refresh(plan)
    return plan


def format_price_usd(price: Decimal) -> str:
    return f"${price:.2f}"
