from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_create_payment_row_defaults(seeded_catalog: dict) -> None:
    from app.db.models.payment import Payment

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        payment = Payment(
            telegram_id=900,
            purpose="purchase",
            plan_id=plan_id,
            group_name="1M-1U-Iran-10G",
            data_cap_mb=10240,
            amount_usd=Decimal("5.00"),
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)

    assert payment.id is not None
    assert payment.status == "pending"
    assert payment.provider == "nowpayments"
    assert payment.vpn_user_id is None
    assert payment.discount_code_id is None
    assert payment.provider_payment_id is None
    assert payment.paid_amount is None


@pytest.mark.asyncio
async def test_payment_id_must_be_unique_for_provider_payment_id(seeded_catalog: dict) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.db.models.payment import Payment

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        session.add(Payment(
            telegram_id=901, purpose="purchase", plan_id=plan_id, group_name="g", data_cap_mb=1,
            amount_usd=Decimal("5.00"), provider_payment_id="np-123",
        ))
        await session.commit()

    async with async_session_maker() as session:
        session.add(Payment(
            telegram_id=902, purpose="purchase", plan_id=plan_id, group_name="g", data_cap_mb=1,
            amount_usd=Decimal("5.00"), provider_payment_id="np-123",
        ))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_payment_status_event_links_to_payment(seeded_catalog: dict) -> None:
    from app.db.models.payment import Payment
    from app.db.models.payment_status_event import PaymentStatusEvent

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        payment = Payment(
            telegram_id=903, purpose="purchase", plan_id=plan_id, group_name="g", data_cap_mb=1,
            amount_usd=Decimal("5.00"),
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)

        session.add(PaymentStatusEvent(payment_id=payment.id, raw_status="waiting"))
        await session.commit()

        rows = (
            await session.execute(select(PaymentStatusEvent).where(PaymentStatusEvent.payment_id == payment.id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].raw_status == "waiting"
    assert rows[0].paid_amount is None
