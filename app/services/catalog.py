from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.plan import Plan
from app.i18n.texts import t

CATEGORIES = ("scroll", "stream", "trial")


async def list_plans(
    session: AsyncSession, *, category: str | None = None, active_only: bool = True
) -> list[Plan]:
    query = select(Plan).order_by(Plan.sort_order, Plan.id)
    if category is not None:
        query = query.where(Plan.category == category)
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


def format_data_cap(data_cap_mb: int) -> str:
    if data_cap_mb % 1024 == 0:
        return f"{data_cap_mb // 1024} GB"
    return f"{data_cap_mb} MB"


_PLAN_NAME_KEYS = {
    "Trial": "plan_name_trial",
    "2 Weeks": "plan_name_2weeks",
    "1 Month": "plan_name_1month",
    "2 Months": "plan_name_2months",
    "3 Months": "plan_name_3months",
}

_CATEGORY_KEYS = {"scroll": "category_scroll", "stream": "category_stream", "trial": "category_trial"}


def plan_display_name(plan: Plan, lang: str) -> str:
    key = _PLAN_NAME_KEYS.get(plan.name)
    return t(key, lang) if key is not None else plan.name


def category_display_name(category: str, lang: str) -> str:
    key = _CATEGORY_KEYS.get(category)
    return t(key, lang) if key is not None else category.title()
