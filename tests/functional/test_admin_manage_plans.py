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
async def test_manage_plans_list_labels_include_group_name(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Migration 0010 leaves three retired capped-Stream plans with exactly
    the same name/category/status as three brand-new Unlimited ones - the
    group name is the only thing that tells the two rows apart at a glance."""
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plans"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    labels = [b["text"] for row in keyboard for b in row]

    assert "🌊 1 Month (1M-1U-Iran-30G) — $12.00 🚫" in labels
    assert "🌊 1 Month (1M-1U-Iran-Unlimited) — $0.00 🚫" in labels
    # Every plan label is distinct now.
    plan_labels = [
        b["text"]
        for row in keyboard
        for b in row
        if b["callback_data"].startswith("adm:settings:plan:") and b["callback_data"].count(":") == 3
    ]
    assert len(set(plan_labels)) == len(plan_labels) == 11


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
@pytest.mark.parametrize("raw_value", ["nan", "NaN", "-nan", "inf"])
async def test_price_edit_rejects_non_finite_input(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, raw_value: str
) -> None:
    """Decimal("nan") parses and quantizes without raising InvalidOperation,
    so it must be rejected explicitly - otherwise the later bounds
    comparison (new_price <= 0) raises uncaught on a NaN operand, the
    admin gets no response, and the FSM is stuck in EditPlanPriceStates.price."""
    from app.services.catalog import get_plan

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, raw_value))

    async with async_session_maker() as session:
        plan = await get_plan(session, 8)
        assert plan is not None
        assert plan.price_usd == Decimal("9.00")  # unchanged

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("valid" in c[1].get("text", "").lower() or "number" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_price_edit_logs_audit_trail(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, caplog: pytest.LogCaptureFixture
) -> None:
    """The audit line must actually render admin/plan/old_price/new_price
    under this app's real logging.basicConfig(), which never renders
    extra= fields - so assert on the rendered message string, not just
    that logger.info was called."""
    import logging

    caplog.set_level(logging.INFO, logger="app.bot.handlers.admin_settings")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:price"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "12.50"))

    audit_records = [r for r in caplog.records if r.name == "app.bot.handlers.admin_settings"]
    rendered = [r.getMessage() for r in audit_records]
    assert any(
        "admin_price_change" in msg
        and f"admin={FAKE_ADMIN_ID}" in msg
        and "plan=8" in msg
        and "old_price=9.00" in msg
        and "new_price=12.50" in msg
        for msg in rendered
    ), rendered


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
async def test_activating_a_zero_priced_plan_is_refused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """The 4 rows migration 0010 inserts are inactive at a $0.00
    placeholder. Activating one before an admin sets a real price would put
    a free paid product in front of customers - refuse it, and write
    nothing."""
    from app.services.catalog import get_plan, list_plans

    async with async_session_maker() as session:
        placeholder = next(
            p
            for p in await list_plans(session, active_only=False)
            if p.group_name == "1M-1U-Iran-Unlimited"
        )
    assert placeholder.price_usd == Decimal("0.00")
    assert placeholder.is_active is False

    await dispatcher.feed_update(
        bot, make_callback_update(FAKE_ADMIN_ID, f"adm:settings:plan:{placeholder.id}:toggle")
    )

    async with async_session_maker() as session:
        after = await get_plan(session, placeholder.id)
        assert after is not None
        assert after.is_active is False  # no DB write happened
        assert after.price_usd == Decimal("0.00")

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert any("price above $0.00" in c[1].get("text", "") for c in answered)
    assert any(c[1].get("show_alert") for c in answered)


@pytest.mark.asyncio
async def test_activating_a_priced_plan_still_works(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """The guard must not block the normal path: once a real price is set,
    activation proceeds."""
    from app.services.catalog import get_plan, list_plans, update_plan

    async with async_session_maker() as session:
        placeholder = next(
            p
            for p in await list_plans(session, active_only=False)
            if p.group_name == "1M-1U-Iran-Unlimited"
        )
        await update_plan(session, placeholder.id, price_usd=Decimal("7.00"))

    await dispatcher.feed_update(
        bot, make_callback_update(FAKE_ADMIN_ID, f"adm:settings:plan:{placeholder.id}:toggle")
    )

    async with async_session_maker() as session:
        after = await get_plan(session, placeholder.id)
        assert after is not None
        assert after.is_active is True


@pytest.mark.asyncio
async def test_deactivating_is_never_blocked_by_the_price_floor(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """The guard only gates ACTIVATION - turning a live plan off must stay
    possible whatever its price."""
    from app.services.catalog import get_plan, update_plan

    async with async_session_maker() as session:
        await update_plan(session, 8, price_usd=Decimal("0.00"))

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:plan:8:toggle"))

    async with async_session_maker() as session:
        after = await get_plan(session, 8)
        assert after is not None
        assert after.is_active is False


@pytest.mark.asyncio
async def test_trial_plan_is_exempt_from_the_price_floor(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Trial is a legitimate permanent $0.00 product - it must still be
    re-activatable after being turned off."""
    from app.services.catalog import get_plan, list_plans, update_plan

    async with async_session_maker() as session:
        trial = next(p for p in await list_plans(session, active_only=False) if p.category == "trial")
        assert trial.price_usd == Decimal("0.00")
        await update_plan(session, trial.id, is_active=False)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:settings:plan:{trial.id}:toggle"))

    async with async_session_maker() as session:
        after = await get_plan(session, trial.id)
        assert after is not None
        assert after.is_active is True


@pytest.mark.asyncio
async def test_price_change_does_not_affect_existing_payment_amount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal as _Decimal

    from app.services.catalog import get_plan, update_plan
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(
        self: CryptoProvider, *, order_id: str, amount_usd: _Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        return "https://nowpayments.io/payment/snapshot-test", "np-snapshot-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    async with async_session_maker() as session:
        plan = await get_plan(session, 7)
        assert plan is not None
        payment = await create_crypto_payment(
            session, telegram_id=FAKE_ADMIN_ID, purpose="purchase", plan=plan, vpn_user=None,
            pay_currency="usdttrc20",
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
