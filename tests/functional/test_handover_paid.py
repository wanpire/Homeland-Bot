"""Purchase and renewal on the shared handover sequence.

Both are driven through `confirm_paid_payment`, the ONE path from a paid
invoice to a provisioned service (used by the Plisio callback and the
reconciler alike), then through the same `ho:*` taps the trial uses.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.handover_helpers import latest_device_picker, pair_attachments, tap_through_handover

_LINKS = {
    "iOS": "https://apps.apple.com/openvpn",
    "Android": "https://play.google.com/openvpn",
    "Windows": "https://openvpn.net/windows",
    "macOS": "https://openvpn.net/macos",
}


async def _seed_openvpn_material() -> None:
    from app.services.app_config import set_config
    from app.services.tutorial_delivery import download_link_key
    from app.services.tutorials import upsert_profile

    async with async_session_maker() as session:
        await upsert_profile(session, platform_id=None, name="ir.alonet.ovpn", file_id="ovpn-file-id", file_type="document", text=None)
        for label, url in _LINKS.items():
            await set_config(session, download_link_key(protocol_label="OpenVPN", platform_label=label), url)


def _plan_id(seeded_catalog: dict) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll" and p["name"] == "1 Month")


async def _paid(
    bot: Any, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch, telegram_id: int, *, purpose: str = "purchase"
) -> int:
    """Create an invoice and confirm it; returns the payment id. A renewal
    first buys the account it renews."""
    from app.db.models.payment import Payment
    from app.db.models.vpn_user import VPNUser
    from app.services.catalog import get_plan
    from app.services.payments.confirmation import ACTIVATED, confirm_paid_payment
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    counter = iter(range(1, 100))

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return f"https://plisio.net/invoice/{order_id}", f"plisio-ho-{order_id}-{next(counter)}"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    vpn_user = None
    if purpose == "renew":
        await _paid(bot, seeded_catalog, monkeypatch, telegram_id)
        return await _renew_existing(bot, seeded_catalog, monkeypatch, telegram_id)

    async with async_session_maker() as session:
        plan = await get_plan(session, _plan_id(seeded_catalog))
        payment = await create_crypto_payment(session, telegram_id=telegram_id, purpose=purpose, plan=plan, vpn_user=vpn_user)
    async with async_session_maker() as session:
        row = await session.get(Payment, payment.id)
        result = await confirm_paid_payment(bot, session, row)
    assert result.outcome == ACTIVATED
    return payment.id


async def _renew_existing(bot: Any, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch, telegram_id: int) -> int:
    """Renew the account `telegram_id` already bought; returns the payment id."""
    from app.db.models.payment import Payment
    from app.db.models.vpn_user import VPNUser
    from app.services.catalog import get_plan
    from app.services.payments.confirmation import ACTIVATED, confirm_paid_payment
    from app.services.payments.service import create_crypto_payment

    async with async_session_maker() as session:
        vpn_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == telegram_id))).scalar_one()
        plan = await get_plan(session, _plan_id(seeded_catalog))
        payment = await create_crypto_payment(session, telegram_id=telegram_id, purpose="renew", plan=plan, vpn_user=vpn_user)
    async with async_session_maker() as session:
        row = await session.get(Payment, payment.id)
        result = await confirm_paid_payment(bot, session, row)
    assert result.outcome == ACTIVATED
    return payment.id


def _outgoing(fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    return [c for c in fake_session.calls if c[0] in ("sendMessage", "sendDocument", "sendPhoto", "sendVideo")]


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["purchase", "renew"])
async def test_payment_time_sends_the_credentials_then_the_device_picker(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch, purpose: str
) -> None:
    """A paying customer gets their username and password at once; the
    pickers only decide which setup material follows."""
    await _seed_openvpn_material()
    telegram_id = 5001 if purpose == "purchase" else 5002
    if purpose == "renew":
        # The renewal first buys its account; only look at the renewal.
        await _paid(bot, seeded_catalog, monkeypatch, telegram_id)
        fake_session.reset()
        payment_id = await _renew_existing(bot, seeded_catalog, monkeypatch, telegram_id)
    else:
        payment_id = await _paid(bot, seeded_catalog, monkeypatch, telegram_id)

    out = _outgoing(fake_session)
    assert [c[0] for c in out] == ["sendMessage", "sendMessage"], "credentials, then the device picker"
    credentials, prompt = out[0][1], out[1][1]
    headline = "Your order has been placed successfully" if purpose == "purchase" else "Your renewal was successful"
    assert headline in credentials["text"]
    assert "<b>Username:</b> <code>" in credentials["text"]
    assert "<b>Password:</b> <code>" in credentials["text"]
    assert "reply_markup" not in credentials, "no Tutorial button under the credentials"
    assert "Which device" in prompt["text"]
    picker = latest_device_picker(fake_session, telegram_id)
    assert {"iOS", "Android", "Windows", "macOS"} == set(picker)
    assert picker["iOS"].startswith(f"ho:p:{payment_id}:os:")

    text = " ".join(c[1].get("text") or c[1].get("caption") or "" for c in fake_session.calls)
    for url in _LINKS.values():
        assert url not in text, "no store URLs before a device is chosen"
    assert not any(c[0] == "sendDocument" for c in fake_session.calls), "no config before a device is chosen"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("purpose", "headline"),
    [("purchase", "Your order has been placed successfully"), ("renew", "Your renewal was successful")],
)
async def test_paid_sequence_is_device_protocol_credentials_setup_pair(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
    purpose: str, headline: str,
) -> None:
    await _seed_openvpn_material()
    telegram_id = 5003 if purpose == "purchase" else 5004
    await _paid(bot, seeded_catalog, monkeypatch, telegram_id, purpose=purpose)
    start = len(fake_session.calls)

    await tap_through_handover(dispatcher, bot, fake_session, telegram_id, platform="Windows", protocol="OpenVPN")

    before = [c for c in fake_session.calls[:start] if c[0] == "sendMessage"]
    assert any(headline in c[1]["text"] for c in before), "credentials went out at payment time"
    del fake_session.calls[:start]
    out = _outgoing(fake_session)
    assert [c[0] for c in out] == ["sendDocument", "sendMessage"], "config, one link - the credentials are not resent"

    link = out[1][1]["text"]
    assert _LINKS["Windows"] in link
    assert all(url not in link for label, url in _LINKS.items() if label != "Windows")
    assert not any("ovpn:link:" in str(c[1]) for c in fake_session.calls), "the device is never asked again"

    calls = [c for c in fake_session.calls if c[0] != "answerCallbackQuery"]
    assert calls[-1][0] == "editMessageReplyMarkup"
    assert pair_attachments(fake_session) == [calls[-1][1]], "exactly one pair, at the very end"


@pytest.mark.asyncio
async def test_paid_android_skips_the_protocol_step(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_openvpn_material()
    await _paid(bot, seeded_catalog, monkeypatch, 5005)
    device_cb = latest_device_picker(fake_session, 5005)["Android"]
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(5005, device_cb))

    assert not any(c[0] == "editMessageText" for c in fake_session.calls), "no protocol picker"
    out = _outgoing(fake_session)
    assert [c[0] for c in out] == ["sendDocument", "sendMessage"], "config, then Android's link"
    assert _LINKS["Android"] in out[1][1]["text"]
    assert len(pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_non_android_protocol_picker_offers_both_protocols_and_back(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    payment_id = await _paid(bot, seeded_catalog, monkeypatch, 5006)
    device_cb = latest_device_picker(fake_session, 5006)["iOS"]
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(5006, device_cb))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = {b["text"]: b["callback_data"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert {"OpenVPN", "L2TP"} <= set(buttons)
    assert buttons["⬅️ Back"] == f"ho:p:{payment_id}:back"
    assert _outgoing(fake_session) == []

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(5006, buttons["⬅️ Back"]))
    picker = latest_device_picker(fake_session, 5006)
    assert "menu:root" not in picker.values()


@pytest.mark.asyncio
async def test_another_user_cannot_claim_a_paid_order(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _paid(bot, seeded_catalog, monkeypatch, 5007)
    device_cb = latest_device_picker(fake_session, 5007)["Android"]
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(5999, device_cb))

    assert _outgoing(fake_session) == []
    assert not any(c[0] == "editMessageText" for c in fake_session.calls)


@pytest.mark.asyncio
async def test_an_unpaid_order_cannot_be_claimed(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.payment import Payment

    payment_id = await _paid(bot, seeded_catalog, monkeypatch, 5008)
    async with async_session_maker() as session:
        row = await session.get(Payment, payment_id)
        row.status = "pending"
        await session.commit()
    device_cb = latest_device_picker(fake_session, 5008)["Android"]
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(5008, device_cb))

    assert _outgoing(fake_session) == []


@pytest.mark.asyncio
async def test_paid_orders_run_through_the_same_shared_handover_as_the_trial(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One implementation of the sequence (the trial's twin of this test
    lives in test_trial_flow.py)."""
    import app.bot.handlers.handover as handover_handler

    seen: list[Any] = []

    async def _spy(bot_: Any, telegram_id: int, account: Any, **kwargs: Any) -> bool:
        seen.append(account)
        return True

    await _paid(bot, seeded_catalog, monkeypatch, 5009)
    monkeypatch.setattr(handover_handler, "deliver_handover", _spy)
    await tap_through_handover(dispatcher, bot, fake_session, 5009, platform="Android")

    assert len(seen) == 1 and seen[0].kind == "purchase"


@pytest.mark.asyncio
async def test_persian_payment_prompt(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 5010, None)
        await set_language(session, 5010, "fa")
    await _paid(bot, seeded_catalog, monkeypatch, 5010)

    out = _outgoing(fake_session)
    assert "سفارش شما با موفقیت ثبت شد" in out[0][1]["text"]
    assert "یوزرنیم:" in out[0][1]["text"] and "پسورد:" in out[0][1]["text"]
    assert "روی کدام دستگاه" in out[1][1]["text"]


@pytest.mark.asyncio
async def test_with_no_setup_material_the_pair_goes_on_the_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L2TP on macOS uses the built-in client, so nothing may follow the
    taps - the closing pair must still appear, on the tapped picker."""
    await _paid(bot, seeded_catalog, monkeypatch, 5011)
    start = len(fake_session.calls)

    await tap_through_handover(dispatcher, bot, fake_session, 5011, platform="macOS", protocol="L2TP")

    del fake_session.calls[:start]
    assert _outgoing(fake_session) == []
    assert len(pair_attachments(fake_session)) == 1
