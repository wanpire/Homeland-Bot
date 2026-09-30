"""While sales are disabled, each of the six gated handlers answers with
the paused message and touches neither Plisio nor IBSng. Everything else -
the menus, My Services, a paid invoice - keeps working."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.session import async_session_maker
from tests.factories import make_callback_update, make_photo_message
from tests.fakes.fake_bot_session import FakeBotSession

_PAUSED_EN = "Sales are temporarily paused"


async def _pause() -> None:
    from app.services.sales_status import set_sales_enabled

    async with async_session_maker() as session:
        await set_sales_enabled(session, False)


async def _use_persian(telegram_id: int) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")


def _plan_id(seeded_catalog: dict) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll" and p["name"] == "1 Month")


async def _create_service(seeded_catalog: dict, telegram_id: int) -> Any:
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["id"] == _plan_id(seeded_catalog))
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        return await create_vpn_user(
            session, client, telegram_id=telegram_id, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"], is_trial=False,
        )


def _forbid_invoices(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    async def _no_invoice(self: CryptoProvider, **_: Any) -> tuple[str, str]:
        raise AssertionError("an invoice was created while sales were disabled")

    monkeypatch.setattr(CryptoProvider, "create_invoice", _no_invoice)


async def _payment_count() -> int:
    from app.db.models.payment import Payment

    async with async_session_maker() as session:
        return (await session.execute(select(func.count()).select_from(Payment))).scalar_one()


async def _vpn_user_count(telegram_id: int) -> int:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        return (
            await session.execute(select(func.count()).select_from(VPNUser).where(VPNUser.telegram_id == telegram_id))
        ).scalar_one()


def _last_screen(fake_session: FakeBotSession) -> dict[str, Any]:
    screens = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    return screens[-1][1]


def _assert_paused(screen: dict[str, Any], *, text_fragment: str = _PAUSED_EN, back: str = "🔙 Back to Main Menu") -> None:
    assert text_fragment in screen["text"]
    buttons = [b for row in screen["reply_markup"]["inline_keyboard"] for b in row]
    assert [(b["text"], b["callback_data"]) for b in buttons] == [(back, "menu:root")]


# --- the six gated handlers --------------------------------------------------


@pytest.mark.asyncio
async def test_buy_plan_is_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5101, f"buy:plan:{_plan_id(seeded_catalog)}"))
    _assert_paused(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_buy_confirm_is_blocked_and_creates_no_invoice(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_invoices(monkeypatch)
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5102, f"buy:confirm:{_plan_id(seeded_catalog)}"))
    _assert_paused(_last_screen(fake_session))
    assert await _payment_count() == 0


@pytest.mark.asyncio
async def test_renew_plan_is_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    service = await _create_service(seeded_catalog, 5103)
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5103, f"renew:plan:{service.id}:{_plan_id(seeded_catalog)}"))
    _assert_paused(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_renew_confirm_is_blocked_and_creates_no_invoice(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_invoices(monkeypatch)
    service = await _create_service(seeded_catalog, 5104)
    await _pause()
    await dispatcher.feed_update(
        bot, make_callback_update(5104, f"renew:confirm:{service.id}:{_plan_id(seeded_catalog)}")
    )
    _assert_paused(_last_screen(fake_session))
    assert await _payment_count() == 0


@pytest.mark.asyncio
async def test_trial_entry_is_blocked(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5105, "menu:trial"))
    _assert_paused(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_trial_confirm_is_blocked_and_creates_no_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """An old trial:confirm button from before the pause must not slip through."""
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5106, "trial:confirm"))
    _assert_paused(_last_screen(fake_session))
    assert await _vpn_user_count(5106) == 0


@pytest.mark.asyncio
async def test_trial_from_a_campaign_photo_sends_a_fresh_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A campaign photo's button reuses menu:trial; a photo can't be
    edited into text, so the gate must send a new message instead."""
    await _pause()
    photo = make_photo_message(5107, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(5107, "menu:trial", anchor_message=photo))
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert sent, "expected a fresh message, not an edit"
    _assert_paused(sent[-1][1])


# --- language and custom text ------------------------------------------------


@pytest.mark.asyncio
async def test_persian_user_sees_the_persian_default(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _use_persian(5108)
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5108, f"buy:plan:{_plan_id(seeded_catalog)}"))
    _assert_paused(
        _last_screen(fake_session), text_fragment="فروش موقتاً متوقف شده است", back="🔙 بازگشت به منوی اصلی"
    )


@pytest.mark.asyncio
async def test_custom_message_is_shown_in_the_users_language(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.sales_status import set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "فروش تا فردا بسته است <تعمیرات>")
        await set_custom_paused_message(session, "en", "Closed until tomorrow <maintenance>")
    await _pause()
    await _use_persian(5109)

    await dispatcher.feed_update(bot, make_callback_update(5109, "menu:trial"))
    assert _last_screen(fake_session)["text"] == "فروش تا فردا بسته است &lt;تعمیرات&gt;"

    await dispatcher.feed_update(bot, make_callback_update(5110, "menu:trial"))
    assert _last_screen(fake_session)["text"] == "Closed until tomorrow &lt;maintenance&gt;"


# --- enabled: nothing changes ------------------------------------------------


@pytest.mark.asyncio
async def test_buy_plan_shows_the_price_summary_when_sales_are_enabled(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(5111, f"buy:plan:{_plan_id(seeded_catalog)}"))
    screen = _last_screen(fake_session)
    assert _PAUSED_EN not in screen["text"]
    assert "1 Month" in screen["text"]


@pytest.mark.asyncio
async def test_trial_entry_shows_the_confirm_prompt_when_sales_are_enabled(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(5112, "menu:trial"))
    screen = _last_screen(fake_session)
    assert _PAUSED_EN not in screen["text"]
    assert any(b["callback_data"] == "trial:confirm" for row in screen["reply_markup"]["inline_keyboard"] for b in row)


# --- disabled: the rest of the bot is untouched --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["menu:buy", "buy:category:scroll", "menu:renew"])
async def test_menus_stay_visible_while_paused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    await _pause()
    await dispatcher.feed_update(bot, make_callback_update(5113, data))
    assert _PAUSED_EN not in _last_screen(fake_session)["text"]


@pytest.mark.asyncio
async def test_my_services_and_account_management_work_while_paused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _create_service(seeded_catalog, 5114)
    await _pause()

    for data in (
        "menu:myservices",
        "myservices:list",
        f"myservices:view:{service.id}",
        f"myservices:detail:{service.id}",
        f"myservices:pw:{service.id}",
    ):
        await dispatcher.feed_update(bot, make_callback_update(5114, data))
        assert _PAUSED_EN not in _last_screen(fake_session)["text"], data

    await dispatcher.feed_update(bot, make_callback_update(5114, f"myservices:pwdo:{service.id}"))
    assert "Password: <code>" in _last_screen(fake_session)["text"], "the reset still runs"


@pytest.mark.asyncio
async def test_an_invoice_paid_while_paused_is_still_provisioned(
    bot: Any, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The customer already paid; the switch only stops NEW sales."""
    from app.db.models.payment import Payment
    from app.services.catalog import get_plan
    from app.services.payments.confirmation import ACTIVATED, confirm_paid_payment
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return f"https://plisio.net/invoice/{order_id}", f"plisio-paused-{order_id}"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    async with async_session_maker() as session:
        plan = await get_plan(session, _plan_id(seeded_catalog))
        payment = await create_crypto_payment(session, telegram_id=5115, purpose="purchase", plan=plan, vpn_user=None)

    await _pause()

    async with async_session_maker() as session:
        row = await session.get(Payment, payment.id)
        result = await confirm_paid_payment(bot, session, row)
    assert result.outcome == ACTIVATED
