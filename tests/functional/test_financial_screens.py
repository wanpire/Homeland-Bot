"""The Financial screens (epic part 2)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


async def _payment(*, telegram_id: int, amount: str, status: str, plan_id: int, days_ago: int = 0) -> int:
    from app.db.models.payment import Payment

    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    async with async_session_maker() as session:
        payment = Payment(
            telegram_id=telegram_id, purpose="purchase", plan_id=plan_id, group_name="2W-1U-Iran-5G",
            data_cap_mb=5120, amount_usd=Decimal(amount), provider="plisio", status=status,
            created_at=when, resolved_at=when if status != "pending" else None,
        )
        session.add(payment)
        await session.commit()
        return payment.id


def _plan_id(seeded_catalog: dict) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll")


def _screen(fake_session: FakeBotSession) -> dict[str, Any]:
    screens = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    return screens[-1][1]


def _buttons(fake_session: FakeBotSession) -> dict[str, str | None]:
    markup = _screen(fake_session).get("reply_markup") or {"inline_keyboard": []}
    return {b["text"]: b.get("callback_data") for row in markup["inline_keyboard"] for b in row}


@pytest.mark.asyncio
async def test_revenue_screen_reports_totals_and_providers(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    plan_id = _plan_id(seeded_catalog)
    await _payment(telegram_id=1, amount="10.00", status="paid", plan_id=plan_id)
    await _payment(telegram_id=2, amount="99.00", status="pending", plan_id=plan_id)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:revenue"))

    text = _screen(fake_session)["text"]
    assert "Revenue Overview" in text
    assert "$10.00" in text
    assert "99.00" not in text, "pending money is not revenue"
    assert "Plisio" in text and "Stripe" in text
    assert "adm:fin" in set(_buttons(fake_session).values())


@pytest.mark.asyncio
async def test_revenue_period_buttons_change_the_window(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    plan_id = _plan_id(seeded_catalog)
    await _payment(telegram_id=1, amount="10.00", status="paid", plan_id=plan_id, days_ago=0)
    await _payment(telegram_id=2, amount="40.00", status="paid", plan_id=plan_id, days_ago=45)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:revenue:today"))
    assert "$10.00" in _screen(fake_session)["text"]

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:revenue:all"))
    assert "$50.00" in _screen(fake_session)["text"]


@pytest.mark.asyncio
async def test_payments_list_and_status_filter(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    plan_id = _plan_id(seeded_catalog)
    paid_id = await _payment(telegram_id=11, amount="5.00", status="paid", plan_id=plan_id)
    failed_id = await _payment(telegram_id=12, amount="7.00", status="failed", plan_id=plan_id)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:payments"))
    buttons = _buttons(fake_session)
    assert any(f"adm:fin:payment:{paid_id}" == data for data in buttons.values())
    assert any(f"adm:fin:payment:{failed_id}" == data for data in buttons.values())

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:payments:paid:all:0"))
    buttons = _buttons(fake_session)
    assert any(f"adm:fin:payment:{paid_id}" == data for data in buttons.values())
    assert not any(f"adm:fin:payment:{failed_id}" == data for data in buttons.values())


@pytest.mark.asyncio
async def test_payments_paginate(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.reporting import PAGE_SIZE

    plan_id = _plan_id(seeded_catalog)
    for index in range(PAGE_SIZE + 2):
        await _payment(telegram_id=200 + index, amount="5.00", status="paid", plan_id=plan_id)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:payments"))
    assert "Next ▶️" in _buttons(fake_session)
    assert "Page 1/2" in _screen(fake_session)["text"]

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:payments:all:all:1"))
    assert "Page 2/2" in _screen(fake_session)["text"]
    assert "◀️ Prev" in _buttons(fake_session)


@pytest.mark.asyncio
async def test_user_search_finds_payments_by_username(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.bot_users import record_seen

    plan_id = _plan_id(seeded_catalog)
    async with async_session_maker() as session:
        await record_seen(session, 4242, "someone")
    mine = await _payment(telegram_id=4242, amount="5.00", status="paid", plan_id=plan_id)
    theirs = await _payment(telegram_id=7777, amount="5.00", status="paid", plan_id=plan_id)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:payments:user"))
    assert "Find payments by user" in _screen(fake_session)["text"]

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "@someone"))

    buttons = _buttons(fake_session)
    assert any(f"adm:fin:payment:{mine}" == data for data in buttons.values())
    assert not any(f"adm:fin:payment:{theirs}" == data for data in buttons.values())


@pytest.mark.asyncio
async def test_user_search_reports_a_miss_instead_of_showing_everything(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Falling back to the unfiltered list would quietly answer a
    different question than the one asked."""
    await _payment(telegram_id=7777, amount="5.00", status="paid", plan_id=_plan_id(seeded_catalog))

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:payments:user"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "nobody-at-all"))

    assert "No user matches" in _screen(fake_session)["text"]


@pytest.mark.asyncio
async def test_payment_detail_shows_the_order(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    payment_id = await _payment(telegram_id=4242, amount="12.50", status="paid", plan_id=_plan_id(seeded_catalog))

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:fin:payment:{payment_id}"))

    text = _screen(fake_session)["text"]
    assert f"Payment #{payment_id}" in text
    assert "$12.50" in text and "paid" in text and "plisio" in text
    assert "4242" in text


@pytest.mark.asyncio
async def test_missing_payment_detail_answers_with_an_alert(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:payment:999999"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    ["adm:fin:revenue", "adm:fin:payments", "adm:fin:payments:user", "adm:fin:payment:1", "adm:fin:payments:paid:all:0"],
)
async def test_support_admin_is_refused_every_financial_screen(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, data: str
) -> None:
    await _seed_admin(882, "support")

    await dispatcher.feed_update(bot, make_callback_update(882, data))

    assert not [c for c in fake_session.calls if c[0] == "editMessageText"]
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True
