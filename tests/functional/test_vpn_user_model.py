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
