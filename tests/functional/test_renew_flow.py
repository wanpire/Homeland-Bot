from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


async def _create_service(seeded_catalog: dict, *, telegram_id: int, category: str, name: str, is_trial: bool = False):
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client, telegram_id=telegram_id, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"], is_trial=is_trial,
        )
    return vpn_user


@pytest.mark.asyncio
async def test_list_renewable_services_excludes_trial(seeded_catalog: dict) -> None:
    from app.services.vpn_users import list_renewable_services

    telegram_id = 801
    paid = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)

    async with async_session_maker() as session:
        rows = await list_renewable_services(session, telegram_id)

    assert [vpn_user.id for vpn_user, _plan in rows] == [paid.id]


@pytest.mark.asyncio
async def test_menu_renew_shows_empty_state_when_no_services(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(802, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "don't have any services" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔑 Buy Subscription" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_menu_renew_lists_non_trial_services_only(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 803
    paid = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    texts = [b["text"] for b in buttons]
    assert "1 Month" in texts
    assert not any("trial" in t.lower() for t in texts)
    callback_by_text = {b["text"]: b["callback_data"] for b in buttons}
    assert callback_by_text["1 Month"] == f"renew:service:{paid.id}"


@pytest.mark.asyncio
async def test_menu_renew_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(804, "menu:renew"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_renew_service_shows_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 805
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Renew 1 Month" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🧳 Trip" in buttons
    # Stream has zero active plans after migration 0010 - see
    # test_renew_stream_category_button_hidden_when_no_active_plans.
    assert "🌊 Stream" not in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_service_unknown_id_shows_not_found(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(806, "renew:service:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_service_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 807
    intruder_id = 808
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_service_malformed_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(809, "renew:service:not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_service_out_of_range_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A numerically-valid but out-of-int32-range id (PostgreSQL's
    `integer` column can't hold it) must degrade to the not-found screen,
    not raise an unhandled asyncpg.DataError."""
    await dispatcher.feed_update(bot, make_callback_update(833, "renew:service:2147483648"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_category_shows_scroll_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 810
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:category:{service.id}:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Renew 1 Month" in edited[0][1]["text"]
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    buttons = [b["text"] for b in all_buttons]
    assert "1 Month — $5.00 (10 GB)" in buttons
    assert "2 Months — $9.00 (20 GB)" in buttons

    callback_data_by_text = {b["text"]: b["callback_data"] for b in all_buttons}
    for name in ("1 Month", "2 Months"):
        plan_id = _plan_id(seeded_catalog, category="scroll", name=name)
        matching = next(cb for text, cb in callback_data_by_text.items() if text.startswith(f"{name} — "))
        assert matching == f"renew:plan:{service.id}:{plan_id}"


@pytest.mark.asyncio
async def test_renew_category_invalid_category_redirects_to_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 811
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:category:{service.id}:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Pick a category" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🧳 Trip" in buttons


@pytest.mark.asyncio
async def test_renew_stream_category_button_hidden_when_no_active_plans(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Same dead-end fix as Buy's: Stream has zero active plans after
    migration 0010, so its button must not render - while the Back button
    always does."""
    telegram_id = 834
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    all_buttons = [b for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert not any(b["callback_data"] == f"renew:category:{service.id}:stream" for b in all_buttons)
    assert any(b["callback_data"] == "menu:renew" for b in all_buttons)


@pytest.mark.asyncio
async def test_renew_stream_category_button_reappears_once_a_stream_plan_is_activated(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.services.catalog import list_plans, update_plan

    telegram_id = 835
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    async with async_session_maker() as session:
        stream_plan = next(
            p
            for p in await list_plans(session, active_only=False)
            if p.category == "stream" and p.group_name == "1M-1U-Iran-Unlimited"
        )
        await update_plan(session, stream_plan.id, price_usd=Decimal("7.00"), is_active=True)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    all_buttons = [b for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["callback_data"] == f"renew:category:{service.id}:stream" for b in all_buttons)


@pytest.mark.asyncio
async def test_renew_category_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 812
    intruder_id = 813
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:category:{service.id}:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_shows_price_summary_with_no_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 820
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{plan_id}"))

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
async def test_renew_plan_shows_auto_applied_public_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.services.discounts import create_discount_code

    telegram_id = 821
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="WELCOME10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True
        )

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$4.50" in text
    assert "-10%" in text


@pytest.mark.asyncio
async def test_renew_plan_not_found_shows_gone_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 822
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_plan_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 823
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 824
    intruder_id = 825
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_malformed_plan_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 826
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_out_of_range_plan_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 834
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:2147483648"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_shows_coming_soon_and_does_not_mutate_service(
    dispatcher: Any,
    bot: Any,
    fake_session: FakeBotSession,
    seeded_catalog: dict,
    ibsng_server: FakeIBSngServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.services.ibsng.client import IBSngClient

    telegram_id = 827
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    original_group = service.ibsng_group
    original_plan_id = service.plan_id
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    # No real payment provider is configured - renew_confirm_cb must fall
    # back to the coming-soon screen and leave the service untouched.
    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)

    async with async_session_maker() as session:
        refreshed = await session.get(type(service), service.id)
    assert refreshed.ibsng_group == original_group
    assert refreshed.plan_id == original_plan_id

    async with IBSngClient() as client:
        live_group = await client.get_user_group(username=service.ibsng_username)
    assert live_group == original_group


@pytest.mark.asyncio
async def test_renew_confirm_shows_below_minimum_message(
    dispatcher: Any,
    bot: Any,
    fake_session: FakeBotSession,
    seeded_catalog: dict,
    ibsng_server: FakeIBSngServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telegram_id = 828
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=[], too_low=[("usdttrc20", "12.00"), ("trx", "10.50")], unknown=[])

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "too low" in edited[0][1]["text"].lower()
    assert "$10.50" in edited[0][1]["text"]
    buttons = [b["text"].lower() for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back to plans" in b for b in buttons)


@pytest.mark.asyncio
async def test_renew_confirm_not_found_shows_gone_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 828
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 829
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 830
    intruder_id = 831
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:confirm:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_malformed_ids_degrade_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(832, "renew:confirm:not-a-number:also-not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_pay_creates_payment_and_shows_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.services.payments.crypto_provider import CryptoProvider

    telegram_id = 840
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=["ltc"], too_low=[], unknown=[])
    captured: dict[str, Any] = {}

    async def _fake_create_invoice(
        self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        captured["pay_currency"] = pay_currency
        return "https://nowpayments.io/payment/renewtest", "np-renew-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"renew:pay:{service.id}:{scroll_plan_id}:ltc")
    )

    assert captured["pay_currency"] == "ltc"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "complete your payment" in edited[0][1]["text"].lower()
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    link_button = next(b for b in all_buttons if b["text"] == "🔗 Open Payment Page")
    assert link_button["url"] == "https://nowpayments.io/payment/renewtest"

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.payment import Payment

        rows = (await session.execute(select(Payment).where(Payment.telegram_id == telegram_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].purpose == "renew"
    assert rows[0].vpn_user_id == service.id
    assert rows[0].plan_id == scroll_plan_id


@pytest.mark.asyncio
async def test_renew_confirm_shows_coming_soon_when_provider_not_configured(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    telegram_id = 841
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_price_summary_shows_crypto_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
) -> None:
    telegram_id = 842
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "₿ Pay with Crypto" in buttons
    assert "✅ Renew" not in buttons


@pytest.mark.asyncio
async def test_renew_empty_state_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 840, None)
        await set_language(session, 840, "fa")

    await dispatcher.feed_update(bot, make_callback_update(840, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "تمدید سرویس" in edited[0][1]["text"]
    assert "ندارید" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_renew_summary_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.bot_users import record_seen, set_language

    telegram_id = 841
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trip", name="2 Weeks")
    new_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{new_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "تمدید" in edited[0][1]["text"]
    assert "قیمت:" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_renew_list_shows_current_plan_name_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Regression test: renew_service_keyboard's button label for the
    CURRENT service must go through plan_display_name(lang), not raw
    plan.name - a Persian user must see the localized plan name on the
    'which service do you want to renew?' list, not English."""
    from app.services.bot_users import record_seen, set_language

    telegram_id = 850
    await _create_service(seeded_catalog, telegram_id=telegram_id, category="trip", name="2 Weeks")

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "۲ هفته" in buttons
    assert "2 Weeks" not in buttons


@pytest.mark.asyncio
async def test_renew_category_picker_shows_current_plan_name_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Regression test: _service_display_name must localize the CURRENT
    service's plan name via plan_display_name(lang) before it's
    interpolated into renew_pick_category - previously it returned raw
    plan.name, leaking English into an otherwise-Persian screen."""
    from app.services.bot_users import record_seen, set_language

    telegram_id = 851
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trip", name="2 Weeks")

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "۲ هفته" in text
    assert "2 Weeks" not in text


@pytest.mark.asyncio
async def test_renew_trip_category_button_present(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 860
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    trip_buttons = [b for row in keyboard for b in row if b["callback_data"] == f"renew:category:{service.id}:trip"]
    assert len(trip_buttons) == 1

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:category:{service.id}:trip"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    plan_buttons = [b for row in keyboard for b in row if b["callback_data"].startswith(f"renew:plan:{service.id}:")]
    assert len(plan_buttons) == 1
    assert "2 Weeks" in plan_buttons[0]["text"]


@pytest.mark.asyncio
async def test_renew_summary_shows_current_plan_name_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Regression test: renew_summary_heading's `current=` argument must
    be the localized current plan name - previously only the NEW plan
    (via plan_display_name) and category were localized while the
    CURRENT plan name stayed in English."""
    from app.services.bot_users import record_seen, set_language

    telegram_id = 852
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trip", name="2 Weeks")
    new_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{new_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "۲ هفته" in text
    assert "2 Weeks" not in text


def _patch_report(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payable: list[str],
    too_low: list[tuple[str, str]],
    unknown: list[str],
) -> None:
    """Replaces the live NOWPayments payability lookup with a fixed
    verdict, so each test states exactly which coins can pay."""
    from decimal import Decimal

    from app.bot.handlers import renew as renew_handler
    from app.services.payments.base import PayabilityReport
    from app.services.payments.currencies import PayCurrency

    async def _fake(amount_usd: Decimal) -> PayabilityReport:
        return PayabilityReport(
            payable=[PayCurrency(code=c, label=c.upper()) for c in payable],
            too_low=[(PayCurrency(code=c, label=c.upper()), Decimal(m)) for c, m in too_low],
            unknown=[PayCurrency(code=c, label=c.upper()) for c in unknown],
        )

    monkeypatch.setattr(renew_handler, "check_payability", _fake)


@pytest.mark.asyncio
async def test_renew_confirm_lists_only_payable_coins(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    telegram_id = 851
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=["trx"], too_low=[("usdttrc20", "12.00")], unknown=[])

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = {b["text"]: b.get("callback_data") for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert buttons["TRX"] == f"renew:pay:{service.id}:{scroll_plan_id}:trx"
    assert "USDTTRC20" not in buttons
    assert any("back" in text.lower() for text in buttons)


@pytest.mark.asyncio
async def test_renew_confirm_unavailable_when_lookups_failed(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    telegram_id = 852
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=[], too_low=[], unknown=["usdttrc20", "trx"])

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "couldn't reach the payment provider" in text.lower()


@pytest.mark.asyncio
async def test_renew_pay_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ownership is re-checked on the coin step too - the chooser's
    callback data must not become a way around it."""
    owner_id = 853
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=["trx"], too_low=[], unknown=[])

    await dispatcher.feed_update(bot, make_callback_update(999, f"renew:pay:{service.id}:{scroll_plan_id}:trx"))

    text = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]
    assert "not found" in text.lower()


@pytest.mark.asyncio
async def test_renew_pay_reoffers_the_chooser_when_nowpayments_rejects_the_coin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.bot.handlers import renew as renew_handler
    from app.services.payments import nowpayments
    from app.services.payments.crypto_provider import CryptoProvider

    telegram_id = 854
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    _patch_report(monkeypatch, payable=["trx", "ltc"], too_low=[], unknown=[])
    invalidated: list[str] = []

    async def _reject(
        self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str, pay_currency: str | None = None
    ) -> tuple[str, str]:
        raise nowpayments.PaymentBelowMinimumError("moved")

    async def _fake_invalidate(code: str) -> None:
        invalidated.append(code)

    monkeypatch.setattr(CryptoProvider, "create_invoice", _reject)
    monkeypatch.setattr(renew_handler, "invalidate", _fake_invalidate)
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"renew:pay:{service.id}:{scroll_plan_id}:trx")
    )

    assert invalidated == ["trx"]
    last = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]
    assert "pick another coin" in last["text"].lower()
    buttons = {b["text"] for row in last["reply_markup"]["inline_keyboard"] for b in row}
    assert "LTC" in buttons
