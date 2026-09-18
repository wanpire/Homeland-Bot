from __future__ import annotations

import datetime as dt
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
async def test_myservices_shows_empty_state_when_no_services(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(701, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "don't have any services" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔑 Buy Subscription" in buttons
    assert "🎁 Free Trial" in buttons


@pytest.mark.asyncio
async def test_existing_trial_users_service_still_lists_when_trial_limit_disabled(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    """Turning off trial_limit_enabled must only affect eligibility for a
    NEW trial - a customer who already has a trial VPNUser row keeps full
    access to their existing service (list, view) exactly as before."""
    from app.services.app_config import set_config

    telegram_id = 704
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(service.ibsng_username, "nearest_exp_date", future)

    async with async_session_maker() as session:
        await set_config(session, "trial_limit_enabled", "false")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    texts = [b["text"] for b in buttons]
    assert any(t.startswith("Trial — ✅ Active") for t in texts)

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" not in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_lists_services_with_status_badges(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    telegram_id = 702
    active = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    expired = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="2 Weeks")
    pending = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(active.ibsng_username, "nearest_exp_date", future)
    ibsng_server.set_user_attr(expired.ibsng_username, "nearest_exp_date", past)
    # pending: leave unset - the fake server's default has no nearest_exp_date

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    texts = [b["text"] for b in buttons]
    assert "1 Month — ✅ Active" in texts
    assert "2 Weeks — ⛔ Expired" in texts
    assert sum(1 for t in texts if t.startswith("1 Month — ⏳ Pending")) == 1

    callback_by_text = {b["text"]: b["callback_data"] for b in buttons}
    assert callback_by_text["1 Month — ✅ Active"] == f"myservices:view:{active.id}"
    assert callback_by_text["2 Weeks — ⛔ Expired"] == f"myservices:view:{expired.id}"


@pytest.mark.asyncio
async def test_myservices_detail_shows_plan_status_and_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    telegram_id = 703
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(service.ibsng_username, "nearest_exp_date", future)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "1 Month" in text
    assert "✅ Active until" in text
    assert service.ibsng_username in text
    assert "Password:" in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔄 Resend Setup" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_myservices_detail_password_lookup_failure_falls_back(
    dispatcher: Any,
    bot: Any,
    fake_session: FakeBotSession,
    seeded_catalog: dict,
    ibsng_server: FakeIBSngServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient IBSng failure while re-reading the password must not
    crash the detail screen - it must render with a fallback message
    instead, the same way trial credential delivery already handles this
    exact IBSngClient.get_user_password call (see test_trial_flow.py's
    test_trial_credentials_ibsng_failure_tells_user_to_contact_support)."""
    from app.services.ibsng.client import IBSngClient
    from app.services.ibsng.exceptions import IBSngError

    telegram_id = 709
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(service.ibsng_username, "nearest_exp_date", future)

    async def _boom(self: Any, *, username: str) -> str | None:
        raise IBSngError("IBSng is down")

    monkeypatch.setattr(IBSngClient, "get_user_password", _boom)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "✅ Active until" in text
    assert "unavailable" in text.lower()
    assert "contact support" in text.lower()


@pytest.mark.asyncio
async def test_myservices_detail_shows_pending_status(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 704
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not yet activated" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_unknown_status_shows_badge_and_detail_message(
    dispatcher: Any,
    bot: Any,
    fake_session: FakeBotSession,
    seeded_catalog: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_service_status returns ("unknown", None) when
    client.get_user_expiry raises IBSngError - a path nothing exercised
    before. This matters more than a typical coverage gap:
    myservices_list_keyboard indexes _STATUS_BADGE[status] directly, so
    any status this function can return that isn't a known key would
    crash the WHOLE list screen, not just one row."""
    from app.services.ibsng.client import IBSngClient
    from app.services.ibsng.exceptions import IBSngError

    telegram_id = 716
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    async def _boom(self: Any, *, username: str) -> str | None:
        raise IBSngError("IBSng is down")

    monkeypatch.setattr(IBSngClient, "get_user_expiry", _boom)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b.startswith("1 Month — ⚠️ Unknown") for b in buttons)

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "couldn't check status right now" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_view_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 705
    intruder_id = 706
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()
    assert service.ibsng_username not in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_myservices_view_unknown_id_shows_not_found(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(707, "myservices:view:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_menu_myservices_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(708, "menu:myservices"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)


@pytest.mark.asyncio
async def test_myservices_resend_shows_protocol_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 710
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "which protocol" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "OpenVPN" in buttons
    assert "L2TP" in buttons


@pytest.mark.asyncio
async def test_myservices_resend_openvpn_delivers_directly_without_platform_step(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol

    telegram_id = 711
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        openvpn_id = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:protocol:{openvpn_id}")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "sent" in edited[-1][1]["text"].lower()
    buttons = [b["text"] for row in edited[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔄 Resend Setup" in buttons


@pytest.mark.asyncio
async def test_myservices_resend_l2tp_shows_platform_picker_then_delivers(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    telegram_id = 712
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        ios_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:protocol:{l2tp_id}")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "which device" in edited[-1][1]["text"].lower()

    fake_session.reset()
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:platform:{l2tp_id}:{ios_id}")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "sent" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_resend_does_not_resend_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Grepping for the literal word "password" would be too weak in both
    directions: deliver_setup's guide/profile copy could legitimately
    mention "password" without leaking anything, and a real credential
    leak that doesn't happen to use that word would slip past it. Assert
    the actual username/password values themselves never appear instead."""
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.ibsng.client import IBSngClient

    telegram_id = 713
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    async with async_session_maker() as session, IBSngClient() as client:
        openvpn_id = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one().id
        password = await client.get_user_password(username=service.ibsng_username)
    assert password is not None

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}"))
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:protocol:{openvpn_id}")
    )

    sent = [c for c in fake_session.calls if c[0] in ("sendMessage", "sendPhoto", "sendDocument", "sendVideo")]
    for _, payload in sent:
        text = payload.get("text", "")
        caption = payload.get("caption", "")
        assert service.ibsng_username not in text and service.ibsng_username not in caption
        assert password not in text and password not in caption


@pytest.mark.asyncio
async def test_myservices_resend_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 714
    intruder_id = 715
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"myservices:resend:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_resend_platform_branch_nonexistent_protocol_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """myservices:resend:<id>:platform:<protocol_id>:<platform_id> is
    reachable via an attacker-crafted callback (per the design spec's own
    threat model). A syntactically valid but nonexistent protocol_id must
    not reach deliver_setup - it does `protocol = await session.get(...)`
    then unconditionally accesses `protocol.label`, which would
    AttributeError on a dangling id. It must degrade to the not-found
    screen instead, exactly like an unowned/nonexistent service does."""
    telegram_id = 717
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:platform:999999:1")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_resend_malformed_vpn_user_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """int(parts[2]) (the vpn_user_id) runs BEFORE the ownership check -
    a non-numeric segment must not raise ValueError past it."""
    await dispatcher.feed_update(bot, make_callback_update(718, "myservices:resend:not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_resend_malformed_protocol_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """int(parts[4]) in the "protocol" branch must not raise ValueError on
    a non-numeric segment."""
    telegram_id = 719
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:protocol:not-a-number")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_resend_malformed_platform_ids_degrade_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """int(parts[4])/int(parts[5]) in the "platform" branch must not raise
    ValueError/IndexError on malformed or missing segments."""
    telegram_id = 720
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"myservices:resend:{service.id}:platform:not-a-number")
    )

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_myservices_empty_state_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 710, None)
        await set_language(session, 710, "fa")

    await dispatcher.feed_update(bot, make_callback_update(710, "menu:myservices"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "سرویسی ندارید" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🎁 تست رایگان" in buttons


@pytest.mark.asyncio
async def test_myservices_detail_status_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    import datetime as dt

    from app.services.bot_users import record_seen, set_language

    telegram_id = 711
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(service.ibsng_username, "nearest_exp_date", future)

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:view:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "وضعیت: ✅ فعال" in edited[0][1]["text"]
