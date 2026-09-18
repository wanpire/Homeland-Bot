from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.db.models.group import Group
from app.db.models.plan import Plan
from app.db.session import async_session_maker, engine

_NEW_GROUP_NAMES = (
    "3M-1U-Iran-30G",
    "1M-1U-Iran-Unlimited",
    "2M-1U-Iran-Unlimited",
    "3M-1U-Iran-Unlimited",
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Same invocation conftest.py's `_migrate_test_database` uses."""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
    )


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


@pytest.mark.asyncio
async def test_migration_0010_group_insert_is_idempotent() -> None:
    """The 4 new group names already exist on the live IBSng instance, so
    the bot's own "🔄 Sync IBSng Groups" admin action (sync_groups) can put
    them in `groups` before this migration ever runs. groups.name is
    uniquely indexed, so an unconditional insert would raise a
    duplicate-key violation and abort the whole `alembic upgrade head`
    deploy.

    This exercises the real migration, not a simulation: downgrade to 0009,
    plant a row exactly as sync_groups would, then upgrade back to head.
    Migration 0010 is data-only (it adds no schema), so the round trip
    leaves the schema untouched and conftest.py's `_clean_database`
    restores the seeded rows for the next test either way."""
    try:
        downgrade = _alembic("downgrade", "0009")
        assert downgrade.returncode == 0, f"{downgrade.stdout}\n{downgrade.stderr}"

        async with engine.begin() as conn:
            remaining = (
                await conn.execute(
                    text("SELECT name FROM groups WHERE name = ANY(:names)"),
                    {"names": list(_NEW_GROUP_NAMES)},
                )
            ).scalars().all()
            assert list(remaining) == []  # downgrade really removed them

            # sync_groups gets there first for one of the four.
            await conn.execute(
                text("INSERT INTO groups (name) VALUES (:name)"), {"name": "1M-1U-Iran-Unlimited"}
            )

        upgrade = _alembic("upgrade", "head")
        assert upgrade.returncode == 0, (
            f"migration 0010 aborted on a pre-existing group row:\n{upgrade.stdout}\n{upgrade.stderr}"
        )

        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT name, COUNT(*) FROM groups WHERE name = ANY(:names) GROUP BY name"),
                    {"names": list(_NEW_GROUP_NAMES)},
                )
            ).all()
        assert sorted(tuple(r) for r in rows) == sorted((name, 1) for name in _NEW_GROUP_NAMES)
    finally:
        restore = _alembic("upgrade", "head")
        assert restore.returncode == 0, f"{restore.stdout}\n{restore.stderr}"


@pytest.mark.asyncio
async def test_migration_0010_leaves_a_drifted_plan_row_alone() -> None:
    """Each plan UPDATE pins the row's expected group_name alongside its id,
    so if production data has drifted since the spec's 2026-09-18
    verification the statement is a silent no-op on exactly the drifted row
    - never a mis-deactivation of whatever plan now holds that id. Proven by
    drifting plan 9 off 1M-1U-Iran-30G before re-running the migration: 9
    must survive untouched while its two undrifted siblings still
    deactivate."""
    try:
        downgrade = _alembic("downgrade", "0009")
        assert downgrade.returncode == 0, f"{downgrade.stdout}\n{downgrade.stderr}"

        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE plans SET group_name = '1M-1U-Iran-10G' WHERE id = 9")
            )

        upgrade = _alembic("upgrade", "head")
        assert upgrade.returncode == 0, f"{upgrade.stdout}\n{upgrade.stderr}"

        async with engine.connect() as conn:
            active_by_id = dict(
                (await conn.execute(text("SELECT id, is_active FROM plans WHERE id IN (9, 10, 11)"))).all()
            )
        assert active_by_id[9] is True, "a drifted row must not be deactivated by id alone"
        assert active_by_id[10] is False
        assert active_by_id[11] is False
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE plans SET group_name = '1M-1U-Iran-30G' WHERE id = 9"))
        restore = _alembic("upgrade", "head")
        assert restore.returncode == 0, f"{restore.stdout}\n{restore.stderr}"
