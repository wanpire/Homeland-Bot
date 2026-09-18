from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_full_admin_cannot_open_crypto_settlement(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=723, level="sales"))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(723, "adm:settings:crypto"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert not any("crypto settlement" in c[1].get("text", "").lower() for c in edited)


@pytest.mark.asyncio
async def test_status_screen_shows_not_configured_when_unset(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no settlement address configured yet" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_edit_shows_network_choice_buttons(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:edit"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    keyboard = edited[-1][1]["reply_markup"]["inline_keyboard"]
    callbacks = [b["callback_data"] for row in keyboard for b in row]
    assert "adm:settings:crypto:network:usdttrc20" in callbacks
    assert "adm:settings:crypto:network:usdtbsc" in callbacks
    assert "adm:settings:crypto:network:trx" in callbacks
    assert "adm:settings:crypto:network:ltc" in callbacks


@pytest.mark.asyncio
async def test_choosing_a_network_prompts_for_address(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:usdttrc20"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "usdt (trc20)" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_valid_address_is_saved_and_shown_on_status_screen(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.app_config import get_config
    from app.services.payments import nowpayments

    async def _fake_validate(*, address: str, currency: str) -> tuple[bool, str | None]:
        return True, None

    monkeypatch.setattr(nowpayments, "validate_payout_address", _fake_validate)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:usdttrc20"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"))

    async with async_session_maker() as session:
        assert await get_config(session, "crypto_settlement_address") == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        assert await get_config(session, "crypto_settlement_network") == "usdttrc20"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "saved" in sent[-1][1]["text"].lower()

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "tr7nhqjekqxgtci8q8zy4pl8otszgjlj6t" in edited[-1][1]["text"].lower()
    assert "usdt (trc20)" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_invalid_address_is_rejected_with_nowpayments_message_and_not_saved(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.app_config import get_config
    from app.services.payments import nowpayments

    async def _fake_validate(*, address: str, currency: str) -> tuple[bool, str | None]:
        return False, "Invalid payout address: USDTTRC20 bogus"

    monkeypatch.setattr(nowpayments, "validate_payout_address", _fake_validate)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:usdttrc20"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "bogus"))

    async with async_session_maker() as session:
        assert await get_config(session, "crypto_settlement_address") is None

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "invalid payout address" in sent[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_empty_address_is_rejected_without_calling_nowpayments(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments import nowpayments

    async def _must_not_be_called(*, address: str, currency: str) -> tuple[bool, str | None]:
        raise AssertionError("validate_payout_address must not be called for an empty address")

    monkeypatch.setattr(nowpayments, "validate_payout_address", _must_not_be_called)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:ltc"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "   "))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "non-empty" in sent[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_invalid_address_error_message_is_html_escaped(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOWPayments echoes the submitted address back inside its error
    message (confirmed against the real API) - if it ever contains HTML
    special characters, this must not reach Telegram's HTML parser
    unescaped (parse_mode is HTML app-wide)."""
    from app.services.payments import nowpayments

    async def _fake_validate(*, address: str, currency: str) -> tuple[bool, str | None]:
        return False, "Invalid payout address: USDTTRC20 <script>&bogus"

    monkeypatch.setattr(nowpayments, "validate_payout_address", _fake_validate)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:usdttrc20"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "<script>&bogus"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    text = sent[-1][1]["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;bogus" in text


@pytest.mark.asyncio
async def test_nowpayments_api_failure_shows_clear_message_instead_of_crashing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.app_config import get_config
    from app.services.payments import nowpayments

    async def _boom(*, address: str, currency: str) -> tuple[bool, str | None]:
        raise nowpayments.NowPaymentsError("simulated 500")

    monkeypatch.setattr(nowpayments, "validate_payout_address", _boom)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:ltc"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "LcccccccccccccccccccccccccccccccX"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "couldn't reach nowpayments" in sent[-1][1]["text"].lower()

    async with async_session_maker() as session:
        assert await get_config(session, "crypto_settlement_address") is None


@pytest.mark.asyncio
async def test_unconfigured_nowpayments_shows_clear_message_instead_of_crashing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:trx"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "TXYZ123"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "can't be validated" in sent[-1][1]["text"].lower()
