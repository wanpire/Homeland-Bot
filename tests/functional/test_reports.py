"""The Reports screen and its queries (epic part 4)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


async def _seed_user(telegram_id: int, *, days_ago: int = 0) -> None:
    from app.db.models.bot_user import BotUser

    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    async with async_session_maker() as session:
        session.add(BotUser(telegram_id=telegram_id, username=None, first_seen_at=when))
        await session.commit()


async def _seed_service(*, telegram_id: int, username: str, is_trial: bool = False, days_ago: int = 0) -> None:
    from app.db.models.vpn_user import VPNUser

    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    async with async_session_maker() as session:
        session.add(
            VPNUser(
                telegram_id=telegram_id, ibsng_username=username, ibsng_group="Trial-Iran" if is_trial else "2W-1U-Iran-5G",
                plan_id=None, data_cap_mb=1024, is_trial=is_trial, created_at=when,
            )
        )
        await session.commit()


async def _seed_payment(*, telegram_id: int, amount: str, status: str, plan_id: int, days_ago: int = 0) -> None:
    from app.db.models.payment import Payment

    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    async with async_session_maker() as session:
        session.add(
            Payment(
                telegram_id=telegram_id, purpose="purchase", plan_id=plan_id, group_name="2W-1U-Iran-5G",
                data_cap_mb=5120, amount_usd=Decimal(amount), provider="plisio", status=status,
                created_at=when, resolved_at=when if status != "pending" else None,
            )
        )
        await session.commit()


def _plan_id(seeded_catalog: dict, name: str = "1 Month") -> int:
    return next(
        p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll" and p["name"] == name
    )


def _screen(fake_session: FakeBotSession) -> str:
    return [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]


# --- queries ---


@pytest.mark.asyncio
async def test_signups_are_counted_per_period_and_all_time(seeded_catalog: dict) -> None:
    from app.services.reporting import signup_count

    await _seed_user(6001, days_ago=0)
    await _seed_user(6002, days_ago=45)

    async with async_session_maker() as session:
        today, all_time = await signup_count(session, period="today")
        month, _ = await signup_count(session, period="30d")

    assert today == 1
    assert month == 1
    assert all_time == 2


@pytest.mark.asyncio
async def test_account_breakdown_reports_live_status_and_its_sample(
    seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from app.services.ibsng.client import IBSngClient
    from app.services.reporting import account_breakdown

    for index in range(4):
        await _seed_service(telegram_id=6100 + index, username=f"ir.rep{index:03d}")

    async with async_session_maker() as session, IBSngClient() as client:
        full = await account_breakdown(session, client)
        sampled = await account_breakdown(session, client, limit=2)

    assert full.total == 4 and full.checked == 4 and full.sampled is False
    assert sum(full.counts.values()) == 4
    assert sampled.checked == 2 and sampled.total == 4 and sampled.sampled is True


@pytest.mark.asyncio
async def test_account_breakdown_survives_an_ibsng_outage(
    seeded_catalog: dict, ibsng_server: FakeIBSngServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_service_status never raises; the report degrades to unknown."""
    from app.services import reporting
    from app.services.ibsng.client import IBSngClient
    from app.services import vpn_users

    await _seed_service(telegram_id=6200, username="ir.down01")

    async def _unknown(client: Any, username: str) -> tuple[str, None]:
        return "unknown", None

    monkeypatch.setattr(vpn_users, "get_service_status", _unknown)

    async with async_session_maker() as session, IBSngClient() as client:
        breakdown = await reporting.account_breakdown(session, client)

    assert breakdown.counts.get("unknown") == 1


@pytest.mark.asyncio
async def test_trial_conversion_counts_a_later_payment(seeded_catalog: dict) -> None:
    """A trial taken on the 30th and paid on the 2nd is still a
    conversion, so the numerator is not period-scoped."""
    from app.services.reporting import trial_conversion

    plan_id = _plan_id(seeded_catalog)
    await _seed_service(telegram_id=6301, username="ir.tr0001", is_trial=True, days_ago=5)
    await _seed_service(telegram_id=6302, username="ir.tr0002", is_trial=True, days_ago=5)
    await _seed_payment(telegram_id=6301, amount="10.00", status="paid", plan_id=plan_id, days_ago=0)
    await _seed_payment(telegram_id=6302, amount="10.00", status="pending", plan_id=plan_id, days_ago=0)

    async with async_session_maker() as session:
        conversion = await trial_conversion(session, period="30d")

    assert conversion.trials == 2
    assert conversion.converted == 1
    assert conversion.rate == Decimal("50.0")


@pytest.mark.asyncio
async def test_trial_conversion_with_no_trials_is_zero_not_an_error(seeded_catalog: dict) -> None:
    from app.services.reporting import trial_conversion

    async with async_session_maker() as session:
        conversion = await trial_conversion(session, period="today")

    assert conversion.trials == 0
    assert conversion.rate == Decimal("0.0")


@pytest.mark.asyncio
async def test_top_plans_ranks_paid_orders_only(seeded_catalog: dict) -> None:
    from app.services.reporting import top_plans

    monthly = _plan_id(seeded_catalog, "1 Month")
    two_months = _plan_id(seeded_catalog, "2 Months")
    for index in range(3):
        await _seed_payment(telegram_id=6400 + index, amount="5.00", status="paid", plan_id=monthly)
    await _seed_payment(telegram_id=6410, amount="9.00", status="paid", plan_id=two_months)
    await _seed_payment(telegram_id=6411, amount="9.00", status="pending", plan_id=two_months)

    async with async_session_maker() as session:
        plans = await top_plans(session, period="all")

    assert plans[0].plan_name == "1 Month" and plans[0].orders == 3
    assert plans[1].plan_name == "2 Months" and plans[1].orders == 1
    assert plans[1].revenue == Decimal("9.00"), "the pending order must not be counted"


# --- the screen ---


@pytest.mark.asyncio
async def test_reports_screen_renders_every_section(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    plan_id = _plan_id(seeded_catalog)
    await _seed_user(6500)
    await _seed_service(telegram_id=6500, username="ir.rp0001", is_trial=True)
    await _seed_payment(telegram_id=6500, amount="7.00", status="paid", plan_id=plan_id)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports:overview"))

    text = _screen(fake_session)
    assert "Reports" in text
    assert "Signups:" in text
    assert "$7.00" in text
    assert "Trial conversion" in text
    assert "Top plans" in text
    assert "1 Month" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["today", "7d", "30d", "all"])
async def test_every_period_renders(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    ibsng_server: FakeIBSngServer, period: str,
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:reports:overview:{period}"))

    assert "Reports" in _screen(fake_session)


@pytest.mark.asyncio
async def test_empty_database_reports_zeroes_rather_than_crashing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports:overview:all"))

    text = _screen(fake_session)
    assert "No accounts yet." in text
    assert "No paid orders in this period." in text


@pytest.mark.asyncio
async def test_support_admin_is_refused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _seed_admin(6600, "support")

    await dispatcher.feed_update(bot, make_callback_update(6600, "adm:reports:overview"))

    assert not [c for c in fake_session.calls if c[0] == "editMessageText"]
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True
