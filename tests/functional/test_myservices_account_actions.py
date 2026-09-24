"""My Services: the root menu, the account action menu, and Reset Password."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


async def _create_service(seeded_catalog: dict, *, telegram_id: int, category: str = "scroll",
                          name: str = "1 Month", is_trial: bool = False):  # type: ignore[no-untyped-def]
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        return await create_vpn_user(
            session, client, telegram_id=telegram_id, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"], is_trial=is_trial,
        )


def _last_edit(fake_session: FakeBotSession) -> dict[str, Any]:
    return [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]


def _buttons(payload: dict[str, Any]) -> dict[str, str]:
    return {b["text"]: b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row}


async def _fa(telegram_id: int) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")


# --- Root menu -----------------------------------------------------------


@pytest.mark.asyncio
async def test_root_menu_matches_the_requested_structure_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _fa(6001)
    await dispatcher.feed_update(bot, make_callback_update(6001, "menu:myservices"))

    payload = _last_edit(fake_session)
    assert payload["text"] == "🛍️ <b>سرویس‌های من</b>\n\nیک گزینه را انتخاب کنید:"
    rows = [[b["text"] for b in row] for row in payload["reply_markup"]["inline_keyboard"]]
    assert rows == [["📋 لیست اکانت‌های من"], ["➕ افزودن اکانت جدید"], ["🔙 بازگشت به منو"]]
    assert list(_buttons(payload).values()) == ["myservices:list", "menu:buy", "menu:root"]


@pytest.mark.asyncio
async def test_add_new_account_is_the_existing_buy_flow(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(6002, "menu:buy"))
    buy_screen = _last_edit(fake_session)["text"]
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(6002, "menu:myservices"))
    await dispatcher.feed_update(bot, make_callback_update(6002, _buttons(_last_edit(fake_session))["➕ Add New Account"]))

    assert _last_edit(fake_session)["text"] == buy_screen


@pytest.mark.asyncio
async def test_list_back_returns_to_the_root_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _create_service(seeded_catalog, telegram_id=6003)
    await dispatcher.feed_update(bot, make_callback_update(6003, "myservices:list"))
    assert _buttons(_last_edit(fake_session))["🔙 Back"] == "menu:myservices"


# --- Account action menu -------------------------------------------------


@pytest.mark.asyncio
async def test_account_menu_offers_every_action(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _fa(6004)
    service = await _create_service(seeded_catalog, telegram_id=6004)
    await dispatcher.feed_update(bot, make_callback_update(6004, f"myservices:view:{service.id}"))

    payload = _last_edit(fake_session)
    assert service.ibsng_username in payload["text"]
    assert _buttons(payload) == {
        "🗓 مشاهده اطلاعات اکانت": f"myservices:detail:{service.id}",
        "♻️ تمدید یا ارتقا اشتراک": f"renew:service:{service.id}",
        "🔑 تغییر پسورد": f"myservices:pw:{service.id}",
        "🔄 تغییر مالکیت": f"myservices:xfer:{service.id}",
        "🔙 بازگشت": "myservices:list",
        "🔙 بازگشت به منو": "menu:root",
    }


@pytest.mark.asyncio
async def test_a_trial_has_no_renew_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _create_service(seeded_catalog, telegram_id=6005, category="trial", name="Trial", is_trial=True)
    await dispatcher.feed_update(bot, make_callback_update(6005, f"myservices:view:{service.id}"))

    payload = _last_edit(fake_session)
    assert "(Trial)" in payload["text"]
    assert not any(cb.startswith("renew:") for cb in _buttons(payload).values())


@pytest.mark.asyncio
async def test_info_screen_keeps_resend_setup_and_goes_back_to_the_menu(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    service = await _create_service(seeded_catalog, telegram_id=6006)
    await dispatcher.feed_update(bot, make_callback_update(6006, f"myservices:detail:{service.id}"))

    assert _buttons(_last_edit(fake_session)) == {
        "🔄 Resend Setup": f"myservices:resend:{service.id}",
        "🔙 Back": f"myservices:view:{service.id}",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["myservices:detail:abc", "myservices:detail:99999999999", "myservices:view:"])
async def test_malformed_ids_read_as_not_found(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(6007, data))
    assert "not found" in _last_edit(fake_session)["text"].lower()


# --- Reset Password ------------------------------------------------------


async def _ibsng_password(ibsng_server: FakeIBSngServer, username: str) -> str:
    from app.services.ibsng.client import IBSngClient

    async with IBSngClient() as client:
        return await client.get_user_password(username=username)


@pytest.mark.asyncio
async def test_password_reset_asks_first_and_changes_nothing_until_confirmed(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    service = await _create_service(seeded_catalog, telegram_id=6010)
    before = await _ibsng_password(ibsng_server, service.ibsng_username)

    await dispatcher.feed_update(bot, make_callback_update(6010, f"myservices:pw:{service.id}"))

    payload = _last_edit(fake_session)
    assert "new password will be generated" in payload["text"]
    assert _buttons(payload)["✅ Yes, generate a new password"] == f"myservices:pwdo:{service.id}"
    assert await _ibsng_password(ibsng_server, service.ibsng_username) == before


@pytest.mark.asyncio
async def test_confirming_sets_a_new_ibsng_password_and_shows_it(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from app.db.models.vpn_user import VPNUser

    service = await _create_service(seeded_catalog, telegram_id=6011)
    before = await _ibsng_password(ibsng_server, service.ibsng_username)

    await dispatcher.feed_update(bot, make_callback_update(6011, f"myservices:pwdo:{service.id}"))

    after = await _ibsng_password(ibsng_server, service.ibsng_username)
    assert after != before
    text = _last_edit(fake_session)["text"]
    assert f"Username: <code>{service.ibsng_username}</code>" in text, "the username is unchanged"
    assert f"Password: <code>{after}</code>" in text
    async with async_session_maker() as session:
        assert (await session.get(VPNUser, service.id)).password_changed_at is not None


@pytest.mark.asyncio
async def test_a_second_reset_within_30_days_is_refused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    service = await _create_service(seeded_catalog, telegram_id=6012)
    await dispatcher.feed_update(bot, make_callback_update(6012, f"myservices:pwdo:{service.id}"))
    first = await _ibsng_password(ibsng_server, service.ibsng_username)

    await dispatcher.feed_update(bot, make_callback_update(6012, f"myservices:pw:{service.id}"))
    assert "30 day(s)" in _last_edit(fake_session)["text"]
    await dispatcher.feed_update(bot, make_callback_update(6012, f"myservices:pwdo:{service.id}"))
    assert "changed recently" in _last_edit(fake_session)["text"]
    assert await _ibsng_password(ibsng_server, service.ibsng_username) == first


@pytest.mark.asyncio
async def test_the_cooldown_lapses_after_30_days(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.vpn_user import VPNUser

    service = await _create_service(seeded_catalog, telegram_id=6013)
    async with async_session_maker() as session:
        row = await session.get(VPNUser, service.id)
        row.password_changed_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(6013, f"myservices:pw:{service.id}"))
    assert "new password will be generated" in _last_edit(fake_session)["text"]


@pytest.mark.asyncio
async def test_another_users_password_cannot_be_reset(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    service = await _create_service(seeded_catalog, telegram_id=6014)
    before = await _ibsng_password(ibsng_server, service.ibsng_username)

    await dispatcher.feed_update(bot, make_callback_update(6999, f"myservices:pwdo:{service.id}"))

    assert "not found" in _last_edit(fake_session)["text"].lower()
    assert await _ibsng_password(ibsng_server, service.ibsng_username) == before


@pytest.mark.asyncio
async def test_an_account_outside_homelands_groups_is_never_modified(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    ibsng_server: FakeIBSngServer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The IBSng instance is shared with AloBot: an account moved into one
    of its groups must be refused, never have its password rotated."""
    from app.db.models.vpn_user import VPNUser
    from app.services.ibsng.client import IBSngClient

    service = await _create_service(seeded_catalog, telegram_id=6015)
    before = await _ibsng_password(ibsng_server, service.ibsng_username)

    async def _alobot_group(self: Any, *, username: str) -> str:
        return "1M-1U-Prime"

    monkeypatch.setattr(IBSngClient, "get_user_group", _alobot_group)
    await dispatcher.feed_update(bot, make_callback_update(6015, f"myservices:pwdo:{service.id}"))

    assert "contact support" in _last_edit(fake_session)["text"]
    assert await _ibsng_password(ibsng_server, service.ibsng_username) == before
    async with async_session_maker() as session:
        assert (await session.get(VPNUser, service.id)).password_changed_at is None


@pytest.mark.asyncio
async def test_an_ibsng_failure_is_reported_kindly_and_stamps_nothing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.ibsng.client import IBSngClient
    from app.services.ibsng.exceptions import IBSngError

    service = await _create_service(seeded_catalog, telegram_id=6016)

    async def _down(self: Any, *, username: str, new_password: str) -> None:
        raise IBSngError("IBSng call 'user.updateUserAttrs' could not reach server: timed out")

    monkeypatch.setattr(IBSngClient, "change_user_password", _down)
    await dispatcher.feed_update(bot, make_callback_update(6016, f"myservices:pwdo:{service.id}"))

    text = _last_edit(fake_session)["text"]
    assert "try again shortly" in text
    assert "timed out" not in text, "no raw IBSng error reaches the customer"
    async with async_session_maker() as session:
        assert (await session.get(VPNUser, service.id)).password_changed_at is None


@pytest.mark.asyncio
async def test_new_password_lines_are_bidi_safe_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    await _fa(6017)
    service = await _create_service(seeded_catalog, telegram_id=6017)
    await dispatcher.feed_update(bot, make_callback_update(6017, f"myservices:pwdo:{service.id}"))

    new = await _ibsng_password(ibsng_server, service.ibsng_username)
    assert f"‏رمز عبور: ⁨<code>{new}</code>⁩" in _last_edit(fake_session)["text"]


@pytest.mark.asyncio
async def test_the_account_menu_clears_an_abandoned_ownership_prompt(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Back from the Change Ownership prompt must not leave the next text
    message to be read as a recipient."""
    service = await _create_service(seeded_catalog, telegram_id=6018)
    await dispatcher.feed_update(bot, make_callback_update(6018, f"myservices:xfer:{service.id}"))
    await dispatcher.feed_update(bot, make_callback_update(6018, f"myservices:view:{service.id}"))
    fake_session.reset()

    await dispatcher.feed_update(bot, make_message_update(6018, "@somebody"))

    assert not any("No bot user found" in (c[1].get("text") or "") for c in fake_session.calls)
