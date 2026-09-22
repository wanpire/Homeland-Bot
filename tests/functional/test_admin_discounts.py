from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


def _plan_id(seeded_catalog: dict, category: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category)


@pytest.mark.asyncio
async def test_non_sales_admin_cannot_open_discounts(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=511, level="support"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(511, "adm:discounts"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("discount codes" in c[1].get("text", "").lower() for c in edited)


@pytest.mark.asyncio
async def test_create_discount_code_full_wizard(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.db.models.discount_code import DiscountCode

    scroll_id = _plan_id(seeded_catalog, "scroll")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:new"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "welcome10"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "10"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:wizard:plan:{scroll_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:plansdone"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:public"))

    async with async_session_maker() as session:
        discount = (await session.execute(select(DiscountCode).where(DiscountCode.code == "WELCOME10"))).scalar_one()
    assert discount.percent == Decimal("10")
    assert discount.usage_limit is None
    assert discount.plan_ids == str(scroll_id)
    assert discount.is_public is True

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "WELCOME10" in edited[-1][1]["text"]


@pytest.mark.asyncio
async def test_duplicate_code_name_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.discounts import create_discount_code

    async with async_session_maker() as session:
        await create_discount_code(session, code="DUPE", percent=Decimal("5"), usage_limit=None, plan_ids=None)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:new"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "dupe"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("already exists" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_wizard_requires_at_least_one_plan(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:new"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "nonelimit"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "15"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:plansdone"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert any("select at least one plan" in c[1].get("text", "").lower() for c in answered)


@pytest.mark.asyncio
async def test_discount_code_with_html_special_chars_is_escaped_in_detail_view(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Nothing rejects </&/> at creation time (the wizard prompt says
    "letters/numbers" but doesn't enforce it), and the detail screen
    interpolates the code straight into an HTML <b> tag - so an
    unescaped code would break its own detail screen forever. Bypass the
    wizard's typed-message path (normalize_discount_code only
    strips/upper-cases; it doesn't validate characters) by creating the
    row directly through the service, matching what a real admin typing
    a code with a stray '<' or '&' would end up with."""
    from app.services.discounts import create_discount_code

    async with async_session_maker() as session:
        discount = await create_discount_code(
            session, code="A&B<C>", percent=Decimal("10"), usage_limit=None, plan_ids=None
        )

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:view:{discount.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    detail = edited[-1][1]["text"]
    assert "A&amp;B&lt;C&gt;" in detail
    assert "A&B<C>" not in detail


@pytest.mark.asyncio
async def test_toggle_active_flips_status(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.discounts import create_discount_code, get_discount_code

    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="TOGGLE1", percent=Decimal("20"), usage_limit=None, plan_ids=[scroll_id])

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:toggle:{discount.id}"))

    async with async_session_maker() as session:
        refreshed = await get_discount_code(session, discount.id)
    assert refreshed.is_active is False


@pytest.mark.asyncio
async def test_delete_requires_confirmation(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.discounts import create_discount_code, get_discount_code

    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="DELME", percent=Decimal("5"), usage_limit=None, plan_ids=None)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:delete:{discount.id}"))
    async with async_session_maker() as session:
        assert await get_discount_code(session, discount.id) is not None

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:delete:{discount.id}:confirm"))
    async with async_session_maker() as session:
        assert await get_discount_code(session, discount.id) is None


@pytest.mark.asyncio
async def test_edit_all_plans_discount_shows_every_plan_checked(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.catalog import list_plans
    from app.services.discounts import create_discount_code

    async with async_session_maker() as session:
        discount = await create_discount_code(
            session, code="ALLPLANS", percent=Decimal("10"), usage_limit=None, plan_ids=None
        )
        active_plans = await list_plans(session, active_only=True)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:edit:{discount.id}"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "25"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    rows = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_button_texts = [
        btn["text"] for row in rows for btn in row if btn["callback_data"].startswith("adm:discounts:wizard:plan:")
    ]
    assert len(plan_button_texts) == len(active_plans)
    assert plan_button_texts, "expected at least one plan button"
    assert all(text.startswith("☑️") for text in plan_button_texts)


@pytest.mark.asyncio
async def test_edit_shows_current_usage_limit_and_visibility(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.discounts import create_discount_code

    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(
            session, code="HINTME", percent=Decimal("10"), usage_limit=7, plan_ids=[scroll_id], is_public=False
        )

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:edit:{discount.id}"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "20"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("current usage limit: 7" in c[1].get("text", "").lower() for c in sent)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))
    # scroll_id is already pre-selected from the edit prefill; no need to
    # (and mustn't - it would toggle it off) tap it again before "Done".
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:plansdone"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "current visibility: private" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_edit_skips_name_step_and_preserves_code(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.discounts import create_discount_code, get_discount_code

    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="EDITME", percent=Decimal("10"), usage_limit=None, plan_ids=[scroll_id])

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:edit:{discount.id}"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "25"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:unlimited"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:plansdone"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:discounts:wizard:private"))

    async with async_session_maker() as session:
        refreshed = await get_discount_code(session, discount.id)
    assert refreshed.code == "EDITME"
    assert refreshed.percent == Decimal("25")
    assert refreshed.is_public is False


@pytest.mark.asyncio
async def test_discount_detail_shows_performance_from_paid_payments_only(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """A pending order has not earned anything yet, so it must not
    inflate a code's reported revenue."""
    import datetime as dt
    from decimal import Decimal

    from app.db.models.payment import Payment
    from app.db.session import async_session_maker
    from app.services.discounts import create_discount_code

    plan_id = next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll")
    async with async_session_maker() as session:
        code = await create_discount_code(
            session, code="PERF10", percent=Decimal("20"), usage_limit=10, plan_ids=None
        )
        code_id = code.id

    now = dt.datetime.now(dt.timezone.utc)
    async with async_session_maker() as session:
        for amount, original, status in (("8.00", "10.00", "paid"), ("8.00", "10.00", "pending")):
            session.add(
                Payment(
                    telegram_id=515, purpose="purchase", plan_id=plan_id, group_name="2W-1U-Iran-5G",
                    data_cap_mb=5120, amount_usd=Decimal(amount), original_amount_usd=Decimal(original),
                    provider="plisio", status=status, discount_code_id=code_id, created_at=now,
                    resolved_at=now if status == "paid" else None,
                )
            )
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:discounts:view:{code_id}"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "Performance" in text
    assert "Paid orders with this code: 1" in text
    assert "Revenue from this code: $8.00" in text
    assert "Discount given: $2.00" in text
