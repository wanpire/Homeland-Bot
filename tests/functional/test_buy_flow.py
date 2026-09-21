from __future__ import annotations

from typing import Any

import pytest

from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


@pytest.mark.asyncio
async def test_buy_shows_category_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🧳 Trip" in buttons
    # Stream has zero active plans after migration 0010 - see
    # test_buy_stream_category_button_hidden_when_no_active_plans.
    assert "🌊 Stream" not in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_category_shows_scroll_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    buttons = [b["text"] for b in all_buttons]
    assert "1 Month — $5.00 (10 GB)" in buttons
    assert "2 Months — $9.00 (20 GB)" in buttons
    assert any("back" in b.lower() for b in buttons)

    callback_data_by_text = {b["text"]: b["callback_data"] for b in all_buttons}
    for name in ("1 Month", "2 Months"):
        plan_id = _plan_id(seeded_catalog, category="scroll", name=name)
        matching = next(cb for text, cb in callback_data_by_text.items() if text.startswith(f"{name} — "))
        assert matching == f"buy:plan:{plan_id}"


@pytest.mark.asyncio
async def test_buy_stream_category_button_hidden_when_no_active_plans(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """After migration 0010 the old capped-Stream plans are deactivated and
    the new Unlimited ones are not yet priced/activated, so Stream has zero
    active plans. Its button must not render at all - tapping it used to
    land on an empty tier list with no explanation."""
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert not any(b["callback_data"] == "buy:category:stream" for b in all_buttons)
    # ...and the screen is still navigable.
    assert any(b["callback_data"] == "menu:root" for b in all_buttons)


@pytest.mark.asyncio
async def test_buy_stream_category_button_reappears_once_a_stream_plan_is_activated(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from decimal import Decimal

    from app.db.session import async_session_maker
    from app.services.catalog import list_plans, update_plan

    async with async_session_maker() as session:
        stream_plan = next(
            p
            for p in await list_plans(session, active_only=False)
            if p.category == "stream" and p.group_name == "1M-1U-Iran-Unlimited"
        )
        await update_plan(session, stream_plan.id, price_usd=Decimal("7.00"), is_active=True)

    await dispatcher.feed_update(bot, make_callback_update(9991, "menu:buy"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    all_buttons = [b for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["callback_data"] == "buy:category:stream" for b in all_buttons)

    await dispatcher.feed_update(bot, make_callback_update(9991, "buy:category:stream"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    plan_buttons = [
        b for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row
        if b["callback_data"].startswith("buy:plan:")
    ]
    assert [b["callback_data"] for b in plan_buttons] == [f"buy:plan:{stream_plan.id}"]


@pytest.mark.asyncio
async def test_buy_category_invalid_category_redirects_to_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A malformed/spoofed `buy:category:xyz` (and, more to the point,
    `buy:category:trial` — Trial has its own dedicated flow) must not
    silently render an empty tier list; it should bounce back to the
    category picker."""
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "Pick a category" in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🧳 Trip" in buttons


@pytest.mark.asyncio
async def test_buy_category_nonsense_category_redirects_to_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:xyz"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Pick a category" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_menu_buy_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_buy_plan_shows_price_summary_with_no_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "1 Month" in text
    assert "$5.00" in text
    assert "Duration: 30 days" in text
    assert "Data: 10 GB" in text
    assert "<s>" not in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "₿ Pay with Crypto" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_plan_shows_auto_applied_public_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.db.session import async_session_maker
    from app.services.discounts import create_discount_code

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="WELCOME10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True
        )

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$4.50" in text
    assert "-10%" in text


@pytest.mark.asyncio
async def test_buy_plan_ignores_private_discount_codes(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.db.session import async_session_maker
    from app.services.discounts import create_discount_code

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="PRIVATE50", percent=Decimal("50"), usage_limit=None, plan_ids=[plan_id], is_public=False
        )

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$2.50" not in text


@pytest.mark.asyncio
async def test_buy_plan_not_found_shows_gone_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:plan:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_confirm_shows_coming_soon_and_creates_no_account(
    dispatcher: Any,
    bot: Any,
    fake_session: FakeBotSession,
    seeded_catalog: dict,
    ibsng_server: FakeIBSngServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models.vpn_user import VPNUser
    from app.db.session import async_session_maker

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    # No payment provider is configured - buy_confirm_cb must fall back
    # to the coming-soon screen and, crucially, still create no orphan
    # VPN/IBSng account.
    monkeypatch.setattr(get_settings(), "plisio_secret_key", "")
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)

    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser))).scalars().all()
    assert list(rows) == []
    assert ibsng_server.user_count() == 0


@pytest.mark.asyncio
async def test_buy_confirm_not_found_shows_gone_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:confirm:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_buy_plan_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """A crafted `buy:plan:<trial-plan-id>` must not render a normal-looking
    $0.00 purchase screen — Trial is real (category="trial", $0.00) but
    Buy must never expose it; that's menu:trial's job."""
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_confirm_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_buy_confirm_creates_payment_and_shows_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.services.payments.crypto_provider import CryptoProvider

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async def _fake_create_invoice(
        self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str
    ) -> tuple[str, str]:
        return "https://plisio.net/invoice/buytest", "plisio-buy-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "complete your payment" in edited[0][1]["text"].lower()
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    link_button = next(b for b in all_buttons if b["text"] == "🔗 Open Payment Page")
    assert link_button["url"] == "https://plisio.net/invoice/buytest"

    from app.db.session import async_session_maker

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.payment import Payment

        rows = (await session.execute(select(Payment).where(Payment.telegram_id == 999))).scalars().all()
    assert len(rows) == 1
    assert rows[0].purpose == "purchase"
    assert rows[0].plan_id == plan_id
    assert rows[0].provider_payment_id == "plisio-buy-1"


@pytest.mark.asyncio
async def test_buy_confirm_shows_coming_soon_when_provider_not_configured(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    monkeypatch.setattr(get_settings(), "plisio_secret_key", "")
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_buy_confirm_shows_unavailable_message_on_api_error(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments import plisio

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async def _boom(*, order_id: str, amount, description: str):
        raise plisio.PlisioError("simulated failure")

    monkeypatch.setattr(plisio, "create_invoice", _boom)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "couldn't reach the payment provider" in edited[0][1]["text"].lower()



@pytest.mark.asyncio
async def test_buy_price_summary_shows_crypto_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "₿ Pay with Crypto" in buttons
    assert "✅ Buy" not in buttons


@pytest.mark.asyncio
async def test_buy_category_screen_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.session import async_session_maker
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 830, None)
        await set_language(session, 830, "fa")

    await dispatcher.feed_update(bot, make_callback_update(830, "menu:buy"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "خرید اشتراک" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 اسکرول" in buttons


@pytest.mark.asyncio
async def test_trip_category_button_present_and_routes(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    trip_buttons = [b for row in keyboard for b in row if b["callback_data"] == "buy:category:trip"]
    assert len(trip_buttons) == 1

    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:trip"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_buttons = [b for row in keyboard for b in row if b["callback_data"].startswith("buy:plan:")]
    assert len(plan_buttons) == 1
    assert "2 Weeks" in plan_buttons[0]["text"]


@pytest.mark.asyncio
async def test_buy_price_summary_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.db.session import async_session_maker
    from app.services.bot_users import record_seen, set_language

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async with async_session_maker() as session:
        await record_seen(session, 831, None)
        await set_language(session, 831, "fa")

    await dispatcher.feed_update(bot, make_callback_update(831, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "مدت:" in edited[0][1]["text"]
    assert "قیمت:" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_buy_confirm_goes_straight_to_the_payment_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plisio lets the buyer choose their coin on its own invoice page, so
    the bot must not interpose a coin chooser of its own."""
    from decimal import Decimal

    from app.services.payments.crypto_provider import CryptoProvider

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async def _fake_create_invoice(
        self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str
    ) -> tuple[str, str]:
        return "https://plisio.net/invoice/abc", "plisio-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b.get("url") == "https://plisio.net/invoice/abc" for b in buttons)
    assert not any((b.get("callback_data") or "").startswith("buy:pay:") for b in buttons)
