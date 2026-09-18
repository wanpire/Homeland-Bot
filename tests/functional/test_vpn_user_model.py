from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_create_vpn_user_row_linked_to_a_plan() -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        plan = (await list_plans(session))[1]  # "1 Month", 5120 MB
        session.add(
            VPNUser(
                telegram_id=123,
                ibsng_username="gina_vpn",
                ibsng_group=plan.group_name,
                plan_id=plan.id,
                data_cap_mb=plan.data_cap_mb,
            )
        )
        await session.commit()

    async with async_session_maker() as session:
        row = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == "gina_vpn"))).scalar_one()
        assert row.telegram_id == 123
        assert row.data_cap_mb == 5120
        assert row.expires_at is None
        assert row.expiry_reminder_sent_at is None
        assert row.low_quota_reminder_sent_at is None


@pytest.mark.asyncio
async def test_ibsng_username_must_be_unique() -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=1, ibsng_username="dup_vpn", ibsng_group="HL-1M", data_cap_mb=5120))
        await session.commit()

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=2, ibsng_username="dup_vpn", ibsng_group="HL-1M", data_cap_mb=5120))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_plan_id_foreign_key_is_enforced() -> None:
    """vpn_users.plan_id -> plans.id must actually reject a plan that
    doesn't exist, not just document the intent in the model."""
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(
            VPNUser(
                telegram_id=4,
                ibsng_username="orphan_vpn",
                ibsng_group="HL-1M",
                plan_id=987654,
                data_cap_mb=5120,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_is_trial_defaults_false() -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=501, ibsng_username="trial_default_test", ibsng_group="Trial-Iran", data_cap_mb=1024))
        await session.commit()

    async with async_session_maker() as session:
        row = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == "trial_default_test"))).scalar_one()
    assert row.is_trial is False


@pytest.mark.asyncio
async def test_db_no_longer_restricts_trial_vpn_users_per_telegram_id() -> None:
    """The lifetime-once rule is enforced entirely at the app layer now
    (has_used_trial, admin-toggleable via trial_limit_enabled) - migration
    0008 drops the old DB-level unique index specifically so a second
    is_trial=true row for the same telegram_id can succeed when the admin
    has turned the limit off. This is the inverse of the old
    test_only_one_trial_vpn_user_per_telegram_id, which asserted the
    now-removed constraint."""
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=502, ibsng_username="trial_once_a", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=502, ibsng_username="trial_once_b", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 502))).scalars().all()
    assert len(rows) == 2
    assert all(row.is_trial for row in rows)


@pytest.mark.asyncio
async def test_same_telegram_id_can_have_multiple_non_trial_vpn_users() -> None:
    """The partial index only restricts is_trial=true rows - a repeat
    paying customer must still be able to own more than one account."""
    from app.db.models.vpn_user import VPNUser
    from sqlalchemy import func

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=503, ibsng_username="repeat_a", ibsng_group="1M-1U-Iran-10G", data_cap_mb=10240, is_trial=False))
        session.add(VPNUser(telegram_id=503, ibsng_username="repeat_b", ibsng_group="2M-1U-Iran-20G", data_cap_mb=20480, is_trial=False))
        await session.commit()

    async with async_session_maker() as session:
        count = (
            await session.execute(select(func.count()).select_from(VPNUser).where(VPNUser.telegram_id == 503))
        ).scalar_one()
    assert count == 2
