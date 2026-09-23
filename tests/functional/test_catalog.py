from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_active_catalog_after_migration_0010() -> None:
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        plans = await list_plans(session)

    # After migration 0010: old stream plans (9, 10, 11) are deactivated,
    # so only 4 active plans remain (trial, trip, scroll, scroll)
    assert [p.name for p in plans] == [
        "Trial",
        "2 Weeks",
        "1 Month",
        "2 Months",
    ]
    assert [p.category for p in plans] == [
        "trial",
        "trip",
        "scroll",
        "scroll",
    ]
    assert [p.duration_days for p in plans] == [1, 14, 30, 60]
    assert [p.data_cap_mb for p in plans] == [1024, 5120, 10240, 20480]
    assert [p.price_usd for p in plans] == [
        Decimal("0.00"),
        Decimal("3.00"),
        Decimal("5.00"),
        Decimal("9.00"),
    ]
    assert [p.group_name for p in plans] == [
        "Trial-Iran",
        "2W-1U-Iran-5G",
        "1M-1U-Iran-10G",
        "2M-1U-Iran-20G",
    ]


@pytest.mark.asyncio
async def test_list_plans_filters_by_category() -> None:
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        scroll = await list_plans(session, category="scroll")
        stream = await list_plans(session, category="stream")
        trial = await list_plans(session, category="trial")
        trip = await list_plans(session, category="trip")

    assert [p.group_name for p in scroll] == ["1M-1U-Iran-10G", "2M-1U-Iran-20G"]
    # After migration 0010: old stream plans (9, 10, 11) are deactivated,
    # new stream plans are inactive. No active stream plans remain.
    assert [p.group_name for p in stream] == []
    assert [p.group_name for p in trial] == ["Trial-Iran"]
    assert [p.group_name for p in trip] == ["2W-1U-Iran-5G"]


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
    assert len(everything) == 11


@pytest.mark.asyncio
async def test_categories_with_active_plans_excludes_stream_after_migration_0010() -> None:
    """Stream has zero active plans until an admin prices and activates one
    of the new Unlimited tiers - Buy/Renew use this to hide the dead-end
    category button."""
    from app.services.catalog import categories_with_active_plans

    async with async_session_maker() as session:
        categories = await categories_with_active_plans(session)

    assert categories == {"trial", "scroll", "trip"}
    assert "stream" not in categories


@pytest.mark.asyncio
async def test_categories_with_active_plans_reports_stream_once_one_is_activated() -> None:
    from app.services.catalog import categories_with_active_plans, list_plans, update_plan

    async with async_session_maker() as session:
        stream_plan = next(
            p
            for p in await list_plans(session, active_only=False)
            if p.category == "stream" and p.group_name == "1M-1U-Iran-Unlimited"
        )
        await update_plan(session, stream_plan.id, price_usd=Decimal("7.00"), is_active=True)

    async with async_session_maker() as session:
        categories = await categories_with_active_plans(session)

    assert "stream" in categories


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


def test_format_data_cap() -> None:
    from app.services.catalog import format_data_cap

    assert format_data_cap(5120, "en") == "5 GB"
    assert format_data_cap(10240, "en") == "10 GB"
    assert format_data_cap(1536, "en") == "1536 MB"


def test_format_data_cap_unlimited_sentinel() -> None:
    from app.services.catalog import format_data_cap

    assert format_data_cap(0, "en") == "Unlimited"
    assert format_data_cap(0, "fa") == "نامحدود"


def test_format_data_cap_gb_and_mb_still_work_with_lang() -> None:
    from app.services.catalog import format_data_cap

    assert format_data_cap(10240, "en") == "10 GB"
    assert format_data_cap(500, "en") == "500 MB"
    assert format_data_cap(10240, "fa") == "10 GB"


def test_categories_includes_trip() -> None:
    from app.services.catalog import CATEGORIES

    assert "trip" in CATEGORIES


def test_category_display_name_trip() -> None:
    from app.services.catalog import category_display_name

    assert category_display_name("trip", "en") == "🧳 Trip"
    assert category_display_name("trip", "fa") == "🧳 تریپ"


@pytest.mark.asyncio
async def test_plan_display_name_translates_known_names() -> None:
    from app.services.catalog import plan_display_name, list_plans

    async with async_session_maker() as session:
        plans = await list_plans(session)
    trial_plan = next(p for p in plans if p.category == "trial")

    assert plan_display_name(trial_plan, "en") == "Trial"
    assert plan_display_name(trial_plan, "fa") == "تست رایگان"


def test_plan_display_name_falls_back_to_raw_name_for_unknown_plan() -> None:
    from app.db.models.plan import Plan
    from app.services.catalog import plan_display_name

    fake_plan = Plan(name="Custom Weird Plan", category="scroll", duration_days=1, data_cap_mb=1, price_usd="1.00", group_name="x", sort_order=0)
    assert plan_display_name(fake_plan, "en") == "Custom Weird Plan"
    assert plan_display_name(fake_plan, "fa") == "Custom Weird Plan"


def test_category_display_name_translates_known_categories() -> None:
    from app.services.catalog import category_display_name

    assert category_display_name("scroll", "en") == "📜 Scroll"
    assert category_display_name("scroll", "fa") == "📜 اسکرول"
    assert category_display_name("stream", "en") == "🌊 Stream"


def test_category_display_name_falls_back_to_title_case_for_unknown_category() -> None:
    from app.services.catalog import category_display_name

    assert category_display_name("weird", "en") == "Weird"
