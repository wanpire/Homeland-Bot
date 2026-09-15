from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_seed_migration_creates_seven_plans() -> None:
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        plans = await list_plans(session)

    assert [p.name for p in plans] == [
        "Trial",
        "2 Weeks",
        "1 Month",
        "2 Months",
        "1 Month",
        "2 Months",
        "3 Months",
    ]
    assert [p.category for p in plans] == [
        "trial",
        "scroll",
        "scroll",
        "scroll",
        "stream",
        "stream",
        "stream",
    ]
    assert [p.duration_days for p in plans] == [1, 14, 30, 60, 30, 60, 90]
    assert [p.data_cap_mb for p in plans] == [1024, 5120, 10240, 20480, 30720, 61440, 102400]
    assert [p.price_usd for p in plans] == [
        Decimal("0.00"),
        Decimal("3.00"),
        Decimal("5.00"),
        Decimal("9.00"),
        Decimal("12.00"),
        Decimal("20.00"),
        Decimal("29.00"),
    ]
    assert [p.group_name for p in plans] == [
        "Trial-Iran",
        "2W-1U-Iran-5G",
        "1M-1U-Iran-10G",
        "2M-1U-Iran-20G",
        "1M-1U-Iran-30G",
        "2M-1U-Iran-60G",
        "3M-1U-Iran-100G",
    ]


@pytest.mark.asyncio
async def test_list_plans_filters_by_category() -> None:
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        scroll = await list_plans(session, category="scroll")
        stream = await list_plans(session, category="stream")
        trial = await list_plans(session, category="trial")

    assert [p.group_name for p in scroll] == ["2W-1U-Iran-5G", "1M-1U-Iran-10G", "2M-1U-Iran-20G"]
    assert [p.group_name for p in stream] == ["1M-1U-Iran-30G", "2M-1U-Iran-60G", "3M-1U-Iran-100G"]
    assert [p.group_name for p in trial] == ["Trial-Iran"]


@pytest.mark.asyncio
async def test_list_plans_active_only_excludes_inactive() -> None:
    from app.services.catalog import list_plans, update_plan

    async with async_session_maker() as session:
        plans = await list_plans(session)
        await update_plan(session, plans[0].id, is_active=False)

    async with async_session_maker() as session:
        active = await list_plans(session, active_only=True)
        everything = await list_plans(session, active_only=False)

    assert len(active) == 6
    assert len(everything) == 7


@pytest.mark.asyncio
async def test_update_plan_price_and_group() -> None:
    from app.services.catalog import get_plan, list_plans, update_plan

    async with async_session_maker() as session:
        plans = await list_plans(session)
        updated = await update_plan(
            session, plans[1].id, price_usd=Decimal("3.50"), group_name="1M-1U-Iran-10G"
        )

    assert updated.price_usd == Decimal("3.50")
    assert updated.group_name == "1M-1U-Iran-10G"

    async with async_session_maker() as session:
        fetched = await get_plan(session, plans[1].id)
    assert fetched.price_usd == Decimal("3.50")


@pytest.mark.asyncio
async def test_plan_group_name_foreign_key_is_enforced() -> None:
    """plans.group_name -> groups.name must actually reject an unknown
    group, not just document the intent in the model."""
    from app.db.models.plan import Plan

    async with async_session_maker() as session:
        session.add(
            Plan(
                name="Bogus",
                category="scroll",
                duration_days=1,
                data_cap_mb=1,
                price_usd=Decimal("1.00"),
                group_name="NO-SUCH-GROUP",
                sort_order=99,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


def test_format_price_usd() -> None:
    from app.services.catalog import format_price_usd

    assert format_price_usd(Decimal("2.50")) == "$2.50"
    assert format_price_usd(Decimal("30")) == "$30.00"
