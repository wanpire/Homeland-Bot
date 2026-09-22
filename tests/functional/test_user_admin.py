"""The admin's customer detail view (epic part 3)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


async def _seed_user(telegram_id: int, username: str | None = None) -> None:
    from app.services.bot_users import record_seen

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, username)


async def _seed_service(*, telegram_id: int, username: str, plan_id: int | None = None, is_trial: bool = False) -> int:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        vpn_user = VPNUser(
            telegram_id=telegram_id, ibsng_username=username, ibsng_group="2W-1U-Iran-5G",
            plan_id=plan_id, data_cap_mb=5120, is_trial=is_trial,
        )
        session.add(vpn_user)
        await session.commit()
        return vpn_user.id


async def _seed_payment(*, telegram_id: int, amount: str, status: str, plan_id: int) -> None:
    from app.db.models.payment import Payment

    now = dt.datetime.now(dt.timezone.utc)
    async with async_session_maker() as session:
        session.add(
            Payment(
                telegram_id=telegram_id, purpose="purchase", plan_id=plan_id, group_name="2W-1U-Iran-5G",
                data_cap_mb=5120, amount_usd=Decimal(amount), provider="plisio", status=status,
                created_at=now, resolved_at=now if status != "pending" else None,
            )
        )
        await session.commit()


def _plan_id(seeded_catalog: dict) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll")


def _screen(fake_session: FakeBotSession) -> dict[str, Any]:
    screens = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    return screens[-1][1]


def _buttons(fake_session: FakeBotSession) -> dict[str, str | None]:
    markup = _screen(fake_session).get("reply_markup") or {"inline_keyboard": []}
    return {b["text"]: b.get("callback_data") for row in markup["inline_keyboard"] for b in row}


# --- the gathering service ---


@pytest.mark.asyncio
async def test_overview_gathers_services_payments_and_trial_state(
    seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from app.services.ibsng.client import IBSngClient
    from app.services.user_admin import user_overview

    plan_id = _plan_id(seeded_catalog)
    await _seed_user(5001, "someone")
    await _seed_service(telegram_id=5001, username="ir.aaa111", plan_id=plan_id)
    await _seed_payment(telegram_id=5001, amount="10.00", status="paid", plan_id=plan_id)
    await _seed_payment(telegram_id=5001, amount="99.00", status="pending", plan_id=plan_id)
    await _seed_payment(telegram_id=5001, amount="99.00", status="failed", plan_id=plan_id)

    async with async_session_maker() as session, IBSngClient() as client:
        overview = await user_overview(session, client, 5001)

    assert overview is not None
    assert overview.display_name == "@someone"
    assert overview.total_services == 1
    assert overview.services[0].ibsng_username == "ir.aaa111"
    assert overview.payments.paid == 1
    assert overview.payments.total_paid_usd == Decimal("10.00")
    assert overview.payments.pending == 1 and overview.payments.failed == 1
    assert overview.trial_used is False


@pytest.mark.asyncio
async def test_overview_returns_none_for_an_unknown_id(
    seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from app.services.ibsng.client import IBSngClient
    from app.services.user_admin import user_overview

    async with async_session_maker() as session, IBSngClient() as client:
        assert await user_overview(session, client, 999999) is None


@pytest.mark.asyncio
async def test_overview_survives_an_ibsng_outage(
    seeded_catalog: dict, ibsng_server: FakeIBSngServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin opens this screen precisely when something is wrong, so
    an IBSng failure must degrade one line, not blank the page."""
    from app.services.ibsng.client import IBSngClient
    from app.services.ibsng.exceptions import IBSngError
    from app.services import user_admin

    await _seed_user(5002)
    await _seed_service(telegram_id=5002, username="ir.bbb222")

    async def _boom(client: Any, username: str) -> tuple[str, None]:
        raise IBSngError("unreachable")

    async def _status(client: Any, username: str) -> tuple[str, None]:
        return "unknown", None

    monkeypatch.setattr(user_admin, "get_service_status", _status)

    async with async_session_maker() as session, IBSngClient() as client:
        overview = await user_admin.user_overview(session, client, 5002)

    assert overview is not None
    assert overview.services[0].status == "unknown"
    assert overview.services[0].expires_at is None


@pytest.mark.asyncio
async def test_overview_limits_live_lookups(seeded_catalog: dict, ibsng_server: FakeIBSngServer) -> None:
    """Each service costs an IBSng round trip; a long history must not
    turn one screen into a dozen network calls."""
    from app.services.ibsng.client import IBSngClient
    from app.services.user_admin import MAX_LIVE_SERVICES, user_overview

    await _seed_user(5003)
    for index in range(MAX_LIVE_SERVICES + 2):
        await _seed_service(telegram_id=5003, username=f"ir.ccc{index:03d}")

    async with async_session_maker() as session, IBSngClient() as client:
        overview = await user_overview(session, client, 5003)

    assert overview is not None
    assert len(overview.services) == MAX_LIVE_SERVICES
    assert overview.total_services == MAX_LIVE_SERVICES + 2
    assert overview.truncated_services == 2


# --- the screens ---


@pytest.mark.asyncio
async def test_users_menu_offers_find_a_user(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users"))

    assert _buttons(fake_session)["🔍 Find a User"] == "adm:users:find"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["5010", "@finduser", "finduser"])
async def test_search_reaches_the_detail_view(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    ibsng_server: FakeIBSngServer, query: str,
) -> None:
    await _seed_user(5010, "finduser")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:find"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, query))

    text = _screen(fake_session)["text"]
    assert "@finduser" in text
    assert "5010" in text


@pytest.mark.asyncio
async def test_search_miss_reports_it_instead_of_listing_everyone(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _seed_user(5011, "present")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:find"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "absent-person"))

    text = _screen(fake_session)["text"]
    assert "No user matches" in text
    assert "@present" not in text


@pytest.mark.asyncio
async def test_detail_view_shows_services_and_payments(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    plan_id = _plan_id(seeded_catalog)
    await _seed_user(5012, "detailed")
    await _seed_service(telegram_id=5012, username="ir.ddd444", plan_id=plan_id)
    await _seed_payment(telegram_id=5012, amount="12.00", status="paid", plan_id=plan_id)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:view:5012"))

    text = _screen(fake_session)["text"]
    assert "ir.ddd444" in text
    assert "$12.00" in text
    assert "Trial: not used" in text


@pytest.mark.asyncio
async def test_block_toggles_from_the_detail_view(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from app.services.bot_users import is_blocked

    await _seed_user(5013, "blockme")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:toggleblock:5013"))
    async with async_session_maker() as session:
        assert await is_blocked(session, 5013) is True
    assert "✅ Unblock" in _buttons(fake_session)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:toggleblock:5013"))
    async with async_session_maker() as session:
        assert await is_blocked(session, 5013) is False
    assert "🚫 Block" in _buttons(fake_session)


@pytest.mark.asyncio
async def test_payments_link_is_sales_only(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    """Financial is sales-gated, so a support admin is not offered a link
    they would only be refused."""
    await _seed_user(5014, "gated")
    await _seed_admin(5100, "support")
    await _seed_admin(5101, "sales")

    await dispatcher.feed_update(bot, make_callback_update(5100, "adm:users:view:5014"))
    assert not any("Payments" in label for label in _buttons(fake_session))

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(5101, "adm:users:view:5014"))
    assert any("Payments" in label for label in _buttons(fake_session))


@pytest.mark.asyncio
async def test_renew_jump_refuses_a_foreign_ibsng_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    ibsng_server: FakeIBSngServer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This IBSng instance is shared with AloBot: an account that moved
    out of a Homeland group must never be renewed from here."""
    from app.services.ibsng.client import IBSngClient

    await _seed_user(5015, "foreign")
    vpn_user_id = await _seed_service(telegram_id=5015, username="ir.eee555")

    async def _alobot_group(self: IBSngClient, *, username: str) -> str:
        return "1M-2U-Prime"

    monkeypatch.setattr(IBSngClient, "get_user_group", _alobot_group)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renewsvc:{vpn_user_id}"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True
    assert "Homeland" in (answered[-1][1].get("text") or "")


@pytest.mark.asyncio
async def test_renew_jump_offers_the_plan_picker_for_a_homeland_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    ibsng_server: FakeIBSngServer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.ibsng.client import IBSngClient

    await _seed_user(5016, "ours")
    vpn_user_id = await _seed_service(telegram_id=5016, username="ir.fff666")

    async def _homeland_group(self: IBSngClient, *, username: str) -> str:
        return "2W-1U-Iran-5G"

    monkeypatch.setattr(IBSngClient, "get_user_group", _homeland_group)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renewsvc:{vpn_user_id}"))

    assert "ir.fff666" in _screen(fake_session)["text"]
    assert any("adm:users:renew:plan:" in (data or "") for data in _buttons(fake_session).values())


@pytest.mark.asyncio
async def test_a_user_with_nothing_still_renders(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    await _seed_user(5017)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:view:5017"))

    text = _screen(fake_session)["text"]
    assert "None yet" in text
    assert "Paid: 0" in text
