from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_seed_migration_creates_four_plans() -> None:
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        plans = await list_plans(session)

    assert [p.name for p in plans] == ["2 Weeks", "1 Month", "2 Months", "3 Months"]
    assert [p.duration_days for p in plans] == [14, 30, 60, 90]
    assert [p.data_cap_mb for p in plans] == [2048, 5120, 10240, 102400]
    assert [p.price_usd for p in plans] == [Decimal("2.50"), Decimal("5.00"), Decimal("10.00"), Decimal("30.00")]
    assert [p.group_name for p in plans] == ["HL-2W", "HL-1M", "HL-2M", "HL-3M"]


@pytest.mark.asyncio
async def test_list_plans_active_only_excludes_inactive() -> None:
    from app.services.catalog import list_plans, update_plan

    async with async_session_maker() as session:
        plans = await list_plans(session)
        await update_plan(session, plans[0].id, is_active=False)

    async with async_session_maker() as session:
        active = await list_plans(session, active_only=True)
        everything = await list_plans(session, active_only=False)

    assert len(active) == 3
    assert len(everything) == 4


@pytest.mark.asyncio
async def test_update_plan_price_and_group() -> None:
    from app.services.catalog import get_plan, list_plans, update_plan

    async with async_session_maker() as session:
        plans = await list_plans(session)
        updated = await update_plan(session, plans[0].id, price_usd=Decimal("2.99"), group_name="HL-1M")

    assert updated.price_usd == Decimal("2.99")
    assert updated.group_name == "HL-1M"

    async with async_session_maker() as session:
        fetched = await get_plan(session, plans[0].id)
    assert fetched.price_usd == Decimal("2.99")


@pytest.mark.asyncio
async def test_plan_group_name_foreign_key_is_enforced() -> None:
    """plans.group_name -> groups.name must actually reject an unknown
    group, not just document the intent in the model."""
    from app.db.models.plan import Plan

    async with async_session_maker() as session:
        session.add(
            Plan(
                name="Bogus",
                duration_days=1,
                data_cap_mb=1,
                price_usd=Decimal("1.00"),
                group_name="HL-NO-SUCH-GROUP",
                sort_order=99,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


def test_format_price_usd() -> None:
    from app.services.catalog import format_price_usd

    assert format_price_usd(Decimal("2.50")) == "$2.50"
    assert format_price_usd(Decimal("30")) == "$30.00"
