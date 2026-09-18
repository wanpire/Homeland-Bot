from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models.group import Group
from app.db.models.plan import Plan
from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_migration_0010_state() -> None:
    """No special fixture is needed here: conftest.py's `_migrate_test_database`
    (session-scoped, autouse) already runs `alembic upgrade head` before any
    test executes, and `_clean_database` (autouse, runs before every test)
    re-seeds `groups`/`plans` from whatever `seeded_catalog` read back right
    after that migration run - so by the time this test body runs, the DB
    already reflects migration 0010's final state. This test just asserts
    that state; it does not run alembic itself."""
    async with async_session_maker() as session:
        plans_by_id = {
            p.id: p for p in (await session.execute(select(Plan))).scalars().all()
        }

        # Plan 6 recategorized in place - same id, same group, same price.
        trip_plan = plans_by_id[6]
        assert trip_plan.category == "trip"
        assert trip_plan.group_name == "2W-1U-Iran-5G"
        assert trip_plan.price_usd == Decimal("3.00")
        assert trip_plan.is_active is True

        # Old capped-Stream plans deactivated, never deleted.
        for old_stream_id in (9, 10, 11):
            assert plans_by_id[old_stream_id].is_active is False

        # 4 new rows: inactive, $0.00, correct group/category/cap.
        new_rows = {
            p.group_name: p
            for p in plans_by_id.values()
            if p.group_name
            in ("3M-1U-Iran-30G", "1M-1U-Iran-Unlimited", "2M-1U-Iran-Unlimited", "3M-1U-Iran-Unlimited")
        }
        assert len(new_rows) == 4
        for plan in new_rows.values():
            assert plan.is_active is False
            assert plan.price_usd == Decimal("0.00")

        assert new_rows["3M-1U-Iran-30G"].category == "scroll"
        assert new_rows["3M-1U-Iran-30G"].data_cap_mb == 30720
        assert new_rows["3M-1U-Iran-30G"].duration_days == 90

        for group_name, duration_days in (
            ("1M-1U-Iran-Unlimited", 30),
            ("2M-1U-Iran-Unlimited", 60),
            ("3M-1U-Iran-Unlimited", 90),
        ):
            plan = new_rows[group_name]
            assert plan.category == "stream"
            assert plan.data_cap_mb == 0
            assert plan.duration_days == duration_days

        # Nothing was deleted - row count only grew (7 original + 4 new = 11).
        assert len(plans_by_id) == 11

        group_names = {g.name for g in (await session.execute(select(Group))).scalars().all()}
        for name in ("3M-1U-Iran-30G", "1M-1U-Iran-Unlimited", "2M-1U-Iran-Unlimited", "3M-1U-Iran-Unlimited"):
            assert name in group_names
