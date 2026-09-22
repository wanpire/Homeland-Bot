"""The read-only queries behind Financial and Reports.

Payments are seeded directly rather than driven through the bot, so each
figure has exactly one cause.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.db.session import async_session_maker


async def _payment(
    *, telegram_id: int, amount: str, status: str, plan_id: int, provider: str = "plisio",
    days_ago: int = 0, original: str | None = None, discount_code_id: int | None = None,
) -> int:
    from app.db.models.payment import Payment

    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    async with async_session_maker() as session:
        payment = Payment(
            telegram_id=telegram_id, purpose="purchase", plan_id=plan_id, group_name="2W-1U-Iran-5G",
            data_cap_mb=5120, amount_usd=Decimal(amount), provider=provider, status=status,
            original_amount_usd=Decimal(original) if original else None,
            discount_code_id=discount_code_id, created_at=when,
            resolved_at=when if status in ("paid", "failed", "refunded") else None,
        )
        session.add(payment)
        await session.commit()
        return payment.id


def _plan_id(seeded_catalog: dict) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll")


@pytest.mark.asyncio
async def test_revenue_counts_only_paid_rows(seeded_catalog: dict) -> None:
    """Pending money has not arrived and failed money never did."""
    from app.services.reporting import revenue_summary

    plan_id = _plan_id(seeded_catalog)
    await _payment(telegram_id=1, amount="10.00", status="paid", plan_id=plan_id)
    await _payment(telegram_id=2, amount="99.00", status="pending", plan_id=plan_id)
    await _payment(telegram_id=3, amount="99.00", status="failed", plan_id=plan_id)

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period="all")

    assert summary.paid_orders == 1
    assert summary.revenue == Decimal("10.00")
    assert summary.by_status["pending"] == 1
    assert summary.by_status["failed"] == 1


@pytest.mark.asyncio
async def test_period_filtering_excludes_older_rows(seeded_catalog: dict) -> None:
    from app.services.reporting import revenue_summary

    plan_id = _plan_id(seeded_catalog)
    await _payment(telegram_id=1, amount="10.00", status="paid", days_ago=0, plan_id=plan_id)
    await _payment(telegram_id=2, amount="20.00", status="paid", days_ago=10, plan_id=plan_id)
    await _payment(telegram_id=3, amount="40.00", status="paid", days_ago=45, plan_id=plan_id)

    async with async_session_maker() as session:
        assert (await revenue_summary(session, period="today")).revenue == Decimal("10.00")
        assert (await revenue_summary(session, period="7d")).revenue == Decimal("10.00")
        assert (await revenue_summary(session, period="30d")).revenue == Decimal("30.00")
        assert (await revenue_summary(session, period="all")).revenue == Decimal("70.00")


@pytest.mark.asyncio
async def test_average_order_is_zero_rather_than_a_division_error(seeded_catalog: dict) -> None:
    from app.services.reporting import revenue_summary

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period="all")

    assert summary.paid_orders == 0
    assert summary.average_order == Decimal("0.00")


@pytest.mark.asyncio
async def test_by_provider_keeps_known_providers_at_zero(seeded_catalog: dict) -> None:
    """Stripe has never taken a payment; it must still be listed so an
    admin sees it is idle rather than wondering where it went."""
    from app.services.reporting import revenue_summary

    await _payment(telegram_id=1, amount="10.00", status="paid", plan_id=_plan_id(seeded_catalog))

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period="all")

    assert summary.by_provider["plisio"].orders == 1
    assert summary.by_provider["plisio"].revenue == Decimal("10.00")
    assert summary.by_provider["stripe"].orders == 0


@pytest.mark.asyncio
async def test_discounts_given_is_original_minus_charged(seeded_catalog: dict) -> None:
    from app.services.reporting import revenue_summary

    plan_id = _plan_id(seeded_catalog)
    await _payment(telegram_id=1, amount="8.00", original="10.00", status="paid", plan_id=plan_id)
    # No discount: original_amount_usd is NULL and must contribute zero,
    # not be read as a full-price refund.
    await _payment(telegram_id=2, amount="10.00", status="paid", plan_id=plan_id)

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period="all")

    assert summary.revenue == Decimal("18.00")
    assert summary.discounts_given == Decimal("2.00")


@pytest.mark.asyncio
async def test_payment_page_filters_and_paginates(seeded_catalog: dict) -> None:
    from app.services.reporting import PAGE_SIZE, payment_page

    plan_id = _plan_id(seeded_catalog)
    for index in range(PAGE_SIZE + 3):
        await _payment(telegram_id=100 + index, amount="5.00", status="paid", plan_id=plan_id)
    await _payment(telegram_id=999, amount="5.00", status="failed", plan_id=plan_id)

    async with async_session_maker() as session:
        first = await payment_page(session, status=None, provider=None, telegram_id=None, page=0)
        assert len(first.rows) == PAGE_SIZE
        assert first.total == PAGE_SIZE + 4
        assert first.pages == 2

        second = await payment_page(session, status=None, provider=None, telegram_id=None, page=1)
        assert len(second.rows) == 4

        failed = await payment_page(session, status="failed", provider=None, telegram_id=None, page=0)
        assert failed.total == 1

        mine = await payment_page(session, status=None, provider=None, telegram_id=100, page=0)
        assert mine.total == 1

        none_here = await payment_page(session, status=None, provider="stripe", telegram_id=None, page=0)
        assert none_here.total == 0


@pytest.mark.asyncio
async def test_payment_row_shows_a_username_when_known(seeded_catalog: dict) -> None:
    from app.services.bot_users import record_seen
    from app.services.reporting import payment_page

    async with async_session_maker() as session:
        await record_seen(session, 4242, "someone")
    await _payment(telegram_id=4242, amount="5.00", status="paid", plan_id=_plan_id(seeded_catalog))
    await _payment(telegram_id=7777, amount="5.00", status="paid", plan_id=_plan_id(seeded_catalog))

    async with async_session_maker() as session:
        page = await payment_page(session, status=None, provider=None, telegram_id=None, page=0)

    who = {row.telegram_id: row.who for row in page.rows}
    assert who[4242] == "@someone"
    assert who[7777] == "7777"


@pytest.mark.asyncio
async def test_resolve_user_query_accepts_id_and_username(seeded_catalog: dict) -> None:
    from app.services.bot_users import record_seen
    from app.services.reporting import resolve_user_query

    async with async_session_maker() as session:
        await record_seen(session, 4242, "someone")

    async with async_session_maker() as session:
        assert await resolve_user_query(session, "4242") == 4242
        assert await resolve_user_query(session, "@someone") == 4242
        assert await resolve_user_query(session, "SomeOne") == 4242
        assert await resolve_user_query(session, "nobody") is None
        assert await resolve_user_query(session, "   ") is None


@pytest.mark.asyncio
async def test_payment_detail_carries_plan_and_buyer(seeded_catalog: dict) -> None:
    from app.services.bot_users import record_seen
    from app.services.reporting import payment_detail

    plan_id = _plan_id(seeded_catalog)
    async with async_session_maker() as session:
        await record_seen(session, 4242, "someone")
    payment_id = await _payment(
        telegram_id=4242, amount="8.00", original="10.00", status="paid", plan_id=plan_id
    )

    async with async_session_maker() as session:
        detail = await payment_detail(session, payment_id)
        missing = await payment_detail(session, 999999)

    assert detail is not None
    assert detail.username == "someone"
    assert detail.plan_name
    assert detail.payment.original_amount_usd == Decimal("10.00")
    assert missing is None


@pytest.mark.asyncio
async def test_discount_performance_counts_only_paid_payments(seeded_catalog: dict) -> None:
    from app.services.discounts import create_discount_code
    from app.services.reporting import discount_performance

    plan_id = _plan_id(seeded_catalog)
    async with async_session_maker() as session:
        code = await create_discount_code(
            session, code="SUMMER20", percent=Decimal("20"), usage_limit=10, plan_ids=None
        )
        code_id = code.id

    await _payment(telegram_id=1, amount="8.00", original="10.00", status="paid",
                   discount_code_id=code_id, plan_id=plan_id)
    await _payment(telegram_id=2, amount="8.00", original="10.00", status="pending",
                   discount_code_id=code_id, plan_id=plan_id)

    async with async_session_maker() as session:
        performance = await discount_performance(session, code_id)

    assert performance.paid_payments == 1
    assert performance.revenue == Decimal("8.00")
    assert performance.discount_given == Decimal("2.00")
    assert performance.usage_limit == 10
