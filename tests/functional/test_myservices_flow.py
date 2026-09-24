from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


def _plain(text: str) -> str:
    """The text without the invisible bidi marks Persian info lines carry."""
    return re.sub("[\u200f\u2068\u2069]", "", text)


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
    await dispatcher.feed_update(bot, make_callback_update(701, "myservices:list"))

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

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "myservices:list"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    texts = [b["text"] for b in buttons]
    assert f"{service.ibsng_username} — ✅ Active" in texts

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
    expired = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trip", name="2 Weeks")
    pending = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="2 Months")

    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(active.ibsng_username, "nearest_exp_date", future)
    ibsng_server.set_user_attr(expired.ibsng_username, "nearest_exp_date", past)
    # pending: leave unset - the fake server's default has no nearest_exp_date

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "myservices:list"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    callback_by_text = {b["text"]: b["callback_data"] for b in buttons}
    assert callback_by_text[f"{active.ibsng_username} — ✅ Active"] == f"myservices:view:{active.id}"
    assert callback_by_text[f"{expired.ibsng_username} — ⛔ Expired"] == f"myservices:view:{expired.id}"
    assert callback_by_text[f"{pending.ibsng_username} — ⏳ Pending"] == f"myservices:view:{pending.id}"


@pytest.mark.asyncio
async def test_myservices_detail_shows_plan_status_and_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    telegram_id = 703
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    ibsng_server.set_user_attr(service.ibsng_username, "nearest_exp_date", future)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:detail:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "<b>1 Month</b> 🔑" in text
    assert "Status: ✅ Active" in text
    assert "Volume: 10 GB" in text
    assert f"Expires: {future} UTC" in text, "Gregorian YYYY-MM-DD HH:MM, as IBSng stores it"
    assert f"Username: <code>{service.ibsng_username}</code>" in text
    assert "Password: <code>" in text
    assert "\u200f" not in text and "\u2068" not in text, "English lines carry no bidi marks"
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

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:detail:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "Status: ✅ Active" in text
    assert "unavailable" in text.lower()
    assert "contact support" in text.lower()


@pytest.mark.asyncio
async def test_myservices_detail_shows_pending_status(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 704
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:detail:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "Status: ⏳ Pending" in edited[0][1]["text"]
    assert "Expires: starts at first connection" in edited[0][1]["text"]


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

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "myservices:list"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert f"{service.ibsng_username} — ⚠️ Unknown" in buttons

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:detail:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Status: ⚠️ Unknown" in edited[0][1]["text"]
    assert "Expires: —" in edited[0][1]["text"]


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

    await dispatcher.feed_update(bot, make_callback_update(710, "myservices:list"))

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

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:detail:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "وضعیت: ✅ فعال" in _plain(edited[0][1]["text"])
    assert f"تاریخ انقضا: {future} UTC" in _plain(edited[0][1]["text"]), "Gregorian even for a Persian user"


@pytest.mark.asyncio
async def test_myservices_list_labels_by_username_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    """Several trials used to read identically ("تست رایگان — در انتظار");
    the username makes every row distinct, and the status stays localized."""
    from app.services.app_config import set_config
    from app.services.bot_users import record_seen, set_language

    telegram_id = 721
    async with async_session_maker() as session:
        await set_config(session, "trial_limit_enabled", "false")
    first = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)
    second = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "myservices:list"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    labels = [
        b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row
        if b["callback_data"].startswith("myservices:view:")
    ]
    assert labels == [f"{first.ibsng_username} — ⏳ در انتظار", f"{second.ibsng_username} — ⏳ در انتظار"]


@pytest.mark.asyncio
async def test_myservices_detail_shows_plan_name_in_persian(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    """Regression test: _detail_text's heading must localize plan.name
    via plan_display_name(lang) - previously it leaked raw English plan
    names into an otherwise-Persian detail screen."""
    from app.services.bot_users import record_seen, set_language

    telegram_id = 722
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="trip", name="2 Weeks")

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:detail:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "۲ هفته" in text
    assert "2 Weeks" not in text


@pytest.mark.asyncio
async def test_myservices_detail_labels_are_persian_for_persian_user(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    """Regression test: _detail_text used to hardcode "Username:" and
    "Password:" in English on the success path even for a Persian user,
    while the failure path (password_unavailable) was already correctly
    Persian - an inconsistently-translated screen. Must show "نام کاربری:"
    (Username) not "Username:" for a Persian user."""
    from app.services.bot_users import record_seen, set_language

    telegram_id = 723
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    async with async_session_maker() as session:
        await record_seen(session, telegram_id, None)
        await set_language(session, telegram_id, "fa")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"myservices:detail:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "نام کاربری:" in text
    assert "Username:" not in text
    # Each Persian info line: RLM, RTL label, colon, then the LTR value
    # isolated - with the marks outside <code>, so tap-to-copy stays clean.
    assert f"\u200fنام کاربری: \u2068<code>{service.ibsng_username}</code>\u2069" in text
    assert re.search("\u200fرمز عبور: \u2068<code>[^<\u200f\u2068\u2069]+</code>\u2069", text)
