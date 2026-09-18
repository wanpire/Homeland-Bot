from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_full_admin_cannot_open_manage_plans(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=622, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(622, "adm:settings:plans"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("manage plans" in c[1].get("text", "").lower() for c in edited)


@pytest.mark.asyncio
async def test_manage_plans_list_shows_every_plan_grouped(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plans"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_buttons = [b for row in keyboard for b in row if b["callback_data"].startswith("adm:settings:plan:") and b["callback_data"].count(":") == 3]
    # 7 original + 4 new from the Task 1 migration = 11 plan rows total.
    assert len(plan_buttons) == 11


@pytest.mark.asyncio
async def test_manage_plans_detail_view_shows_fields(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:6"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[-1][1]["text"]
    assert "2W-1U-Iran-5G" in text
    assert "$3.00" in text
    assert "trip" in text.lower()


@pytest.mark.asyncio
async def test_price_edit_happy_path(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.catalog import get_plan

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "12.50"))

    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.price_usd == Decimal("12.50")

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("$12.50" in c[1].get("text", "") for c in sent)


@pytest.mark.asyncio
async def test_price_edit_rejects_non_numeric_input(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.catalog import get_plan

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "not-a-number"))

    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.price_usd == Decimal("9.00")  # unchanged

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("valid" in c[1].get("text", "").lower() or "number" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_price_edit_rejects_price_at_or_above_1000(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.catalog import get_plan

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "1000"))

    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.price_usd == Decimal("9.00")  # unchanged


@pytest.mark.asyncio
async def test_toggle_active_hides_plan_from_buy_flow(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:toggle"))

    from app.services.catalog import get_plan
    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.is_active is False

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "menu:buy"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "buy:category:scroll"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_buttons = [b for row in keyboard for b in row if b["callback_data"].startswith("buy:plan:")]
    # Plan 8 ("2 Months" scroll) is now inactive - only plan 7 ("1 Month") remains.
    assert len(plan_buttons) == 1
    assert not any(b["callback_data"] == "buy:plan:8" for b in plan_buttons)


@pytest.mark.asyncio
async def test_price_change_does_not_affect_existing_payment_amount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal as _Decimal

    from app.services.catalog import get_plan, update_plan
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(
        self: CryptoProvider, *, order_id: str, amount_usd: _Decimal, description: str
    ) -> tuple[str, str]:
        return "https://nowpayments.io/payment/snapshot-test", "np-snapshot-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    async with async_session_maker() as session:
        plan = await get_plan(session, 7)
        assert plan is not None
        payment = await create_crypto_payment(
            session, telegram_id=FAKE_ADMIN_ID, purpose="purchase", plan=plan, vpn_user=None,
        )
        original_amount = payment.amount_usd
        payment_id = payment.id

    async with async_session_maker() as session:
        await update_plan(session, 7, price_usd=Decimal("999.00"))

    async with async_session_maker() as session:
        from app.db.models.payment import Payment
        refreshed = await session.get(Payment, payment_id)
        assert refreshed is not None
        assert refreshed.amount_usd == original_amount
        assert refreshed.amount_usd != Decimal("999.00")
