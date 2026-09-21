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
    assert "adm:settings:crypto:network:USDT_TRX" in callbacks
    assert "adm:settings:crypto:network:USDT_TON" in callbacks
    assert "adm:settings:crypto:network:TRX" in callbacks
    assert "adm:settings:crypto:network:LTC" in callbacks


@pytest.mark.asyncio
async def test_choosing_a_network_prompts_for_address(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:USDT_TRX"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "usdt (trc-20)" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_valid_address_is_saved_and_shown_on_status_screen(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:USDT_TRX"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"))

    async with async_session_maker() as session:
        assert await get_config(session, "crypto_settlement_address") == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        assert await get_config(session, "crypto_settlement_network") == "USDT_TRX"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "saved" in sent[-1][1]["text"].lower()

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "tr7nhqjekqxgtci8q8zy4pl8otszgjlj6t" in edited[-1][1]["text"].lower()
    assert "usdt (trc-20)" in edited[-1][1]["text"].lower()



@pytest.mark.asyncio
async def test_empty_address_is_rejected_without_saving(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch,
) -> None:

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:LTC"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "   "))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "non-empty" in sent[-1][1]["text"].lower()






@pytest.mark.asyncio
async def test_saving_an_address_makes_no_outbound_api_call(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plisio documents no address-validation endpoint, and this record is
    an internal note rather than anything wired into the gateway, so
    saving must not reach out to any API."""
    import httpx

    from app.db.session import async_session_maker
    from app.services.app_config import get_config

    async def _must_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("saving a settlement address must make no HTTP call")

    monkeypatch.setattr(httpx.AsyncClient, "get", _must_not_be_called)
    monkeypatch.setattr(httpx.AsyncClient, "post", _must_not_be_called)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:crypto:network:LTC"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "LbXyZexampleLitecoinAddress"))

    async with async_session_maker() as session:
        assert await get_config(session, "crypto_settlement_address") == "LbXyZexampleLitecoinAddress"
        assert await get_config(session, "crypto_settlement_network") == "LTC"
