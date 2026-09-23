from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


@pytest.mark.asyncio
async def test_trial_entry_shows_confirm_for_eligible_user(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_callback_update(801, "menu:trial")
    await dispatcher.feed_update(bot, update)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "24" in edited[0][1]["text"] and "1gb" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("confirm" in b.lower() or "start" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_trial_entry_shows_already_used_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=802, ibsng_username="hl.already1", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    update = make_callback_update(802, "menu:trial")
    await dispatcher.feed_update(bot, update)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "already used" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_trial_confirm_creates_account_then_shows_protocol_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_callback_update(803, "trial:confirm")
    await dispatcher.feed_update(bot, update)

    async with async_session_maker() as session:
        from app.db.models.vpn_user import VPNUser

        vpn_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 803))).scalar_one()
    assert vpn_user.is_trial is True
    assert vpn_user.ibsng_group == "Trial-Iran"
    assert vpn_user.data_cap_mb == 1024

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("l2tp" in b.lower() for b in buttons)
    assert any("openvpn" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_trial_confirm_twice_shows_already_used_second_time(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(804, "trial:confirm"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(804, "menu:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "already used" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_trial_confirm_replayed_creates_no_second_ibsng_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, ibsng_server: FakeIBSngServer
) -> None:
    """`trial:confirm` is a bare callback_data string, so an old message's
    button (or a replayed update) can re-enter this handler without ever
    passing through the menu's eligibility check. Before the fix that was
    a real resource-exhaustion vector against the SHARED production IBSng
    instance: create_vpn_user only learned about the trial-once constraint
    from the local INSERT, i.e. AFTER IBSng had already provisioned an
    account, which was then orphaned - and the handler retried up to 3
    times with a fresh username, so each spammed tap could orphan 3 more.

    So this asserts on IBSng's own state, not just the message shown."""
    from app.db.models.vpn_user import VPNUser

    await dispatcher.feed_update(bot, make_callback_update(808, "trial:confirm"))
    accounts_after_first = ibsng_server.created_usernames()
    assert len(accounts_after_first) == 1

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(808, "trial:confirm"))

    # Asserted FIRST, because it's the actual point: the replayed confirm
    # created no IBSng account at all - not a named one, and not an
    # unnamed half-created one either. (Before the fix this was 4: the
    # original plus one orphan per retry.)
    assert ibsng_server.created_usernames() == accounts_after_first
    assert ibsng_server.user_count() == 1

    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 808))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ibsng_username == accounts_after_first[0]

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "already used" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_trial_confirm_username_collision_does_not_claim_trial_was_used(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exhausting the retry budget on genuine username collisions is a
    transient failure, NOT a spent trial - telling an eligible user their
    trial was "already used" would be flatly wrong and unrecoverable."""
    import app.bot.handlers.trial as trial_handler

    async def _always_taken(*args: Any, **kwargs: Any) -> Any:
        raise trial_handler.VPNUsernameTakenError("collision")

    monkeypatch.setattr(trial_handler, "create_vpn_user", _always_taken)
    await dispatcher.feed_update(bot, make_callback_update(809, "trial:confirm"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"].lower()
    assert "already used" not in text
    assert "try again" in text


async def _ids(protocol: str, platform: str | None = None) -> tuple[int, int | None]:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        protocol_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == protocol))).scalar_one().id
        platform_id = None
        if platform is not None:
            platform_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == platform))).scalar_one().id
    return protocol_id, platform_id


_OVPN_LINKS = {
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
        for label, url in _OVPN_LINKS.items():
            await set_config(session, download_link_key(protocol_label="OpenVPN", platform_label=label), url)


def _outgoing(fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    return [c for c in fake_session.calls if c[0] in ("sendMessage", "sendDocument", "sendPhoto", "sendVideo")]


def _pair_attachments(fake_session: FakeBotSession) -> list[dict[str, Any]]:
    """editMessageReplyMarkup calls that put the Tutorial/Back pair on a message."""
    found = []
    for name, payload in fake_session.calls:
        if name != "editMessageReplyMarkup":
            continue
        rows = (payload.get("reply_markup") or {}).get("inline_keyboard") or []
        callbacks = {b.get("callback_data") for row in rows for b in row}
        if callbacks == {"menu:tutorials", "menu:root"}:
            found.append(payload)
    return found


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["L2TP", "OpenVPN"])
async def test_every_protocol_asks_for_the_device_before_sending_anything(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, protocol: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(805, "trial:confirm"))
    protocol_id, _ = await _ids(protocol)
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(805, f"trial:protocol:{protocol_id}"))

    assert _outgoing(fake_session) == [], "no credentials or files before the device is chosen"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = {b["text"]: b["callback_data"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row}
    _, ios_id = await _ids(protocol, "iOS")
    assert buttons["iOS"] == f"trial:os:{protocol_id}:{ios_id}"
    assert {"iOS", "Android", "Windows", "macOS"} <= set(buttons)
    assert "trial:back_to_protocol" in buttons.values()


@pytest.mark.asyncio
async def test_openvpn_device_pick_sends_credentials_then_that_devices_setup_only(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_openvpn_material()
    await dispatcher.feed_update(bot, make_callback_update(806, "trial:confirm"))
    protocol_id, windows_id = await _ids("OpenVPN", "Windows")
    await dispatcher.feed_update(bot, make_callback_update(806, f"trial:protocol:{protocol_id}"))
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(806, f"trial:os:{protocol_id}:{windows_id}"))

    out = _outgoing(fake_session)
    assert [c[0] for c in out] == ["sendMessage", "sendDocument", "sendMessage"], "credentials, config, link"

    credentials = out[0][1]
    assert "Your trial service is ready" in credentials["text"]
    assert "hl." in credentials["text"] or "ir." in credentials["text"]
    assert "Tutorial section" not in credentials["text"]
    assert "reply_markup" not in credentials, "no early Tutorial button"

    link_text = out[2][1]["text"]
    assert _OVPN_LINKS["Windows"] in link_text
    for other, url in _OVPN_LINKS.items():
        if other != "Windows":
            assert url not in link_text
    assert not any("ovpn:link:" in str(c[1]) for c in fake_session.calls), "device is never asked again"

    pairs = _pair_attachments(fake_session)
    assert len(pairs) == 1


@pytest.mark.asyncio
async def test_the_final_pair_lands_on_the_last_message_of_the_sequence(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_openvpn_material()
    await dispatcher.feed_update(bot, make_callback_update(812, "trial:confirm"))
    protocol_id, ios_id = await _ids("OpenVPN", "iOS")
    await dispatcher.feed_update(bot, make_callback_update(812, f"trial:protocol:{protocol_id}"))
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(812, f"trial:os:{protocol_id}:{ios_id}"))

    calls = [c for c in fake_session.calls if c[0] != "answerCallbackQuery"]
    last_send = max(i for i, c in enumerate(calls) if c[0] in ("sendMessage", "sendDocument"))
    assert _OVPN_LINKS["iOS"] in calls[last_send][1]["text"], "the link is the last thing sent"
    assert calls[-1][0] == "editMessageReplyMarkup", "the pair is attached after it"
    assert _pair_attachments(fake_session) == [calls[-1][1]]


@pytest.mark.asyncio
async def test_with_no_setup_material_the_pair_goes_on_the_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """L2TP on macOS uses the built-in client: nothing may be configured
    beyond the credentials, and the pair must still appear."""
    await dispatcher.feed_update(bot, make_callback_update(813, "trial:confirm"))
    protocol_id, macos_id = await _ids("L2TP", "macOS")
    await dispatcher.feed_update(bot, make_callback_update(813, f"trial:protocol:{protocol_id}"))
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(813, f"trial:os:{protocol_id}:{macos_id}"))

    out = _outgoing(fake_session)
    assert len(out) == 1 and "Your trial service is ready" in out[0][1]["text"]
    assert len(_pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_l2tp_device_pick_sends_that_devices_guide_after_the_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.tutorials import upsert_guide

    protocol_id, ios_id = await _ids("L2TP", "iOS")
    async with async_session_maker() as session:
        guide = await upsert_guide(session, platform_id=ios_id, protocol_id=protocol_id, media_file_id=None, media_type=None)
        guide.body_html = "iOS L2TP steps"
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(807, "trial:confirm"))
    await dispatcher.feed_update(bot, make_callback_update(807, f"trial:protocol:{protocol_id}"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(807, f"trial:os:{protocol_id}:{ios_id}"))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert len(texts) == 2
    assert "Your trial service is ready" in texts[0]
    assert "<b>Plan:</b> Trial" in texts[0]
    assert "1 day from first connection" in texts[0]
    assert texts[1] == "iOS L2TP steps"
    assert len(_pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_android_l2tp_is_refused_before_any_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(814, "trial:confirm"))
    protocol_id, android_id = await _ids("L2TP", "Android")
    await dispatcher.feed_update(bot, make_callback_update(814, f"trial:protocol:{protocol_id}"))
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(814, f"trial:os:{protocol_id}:{android_id}"))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert len(texts) == 1 and "OpenVPN" in texts[0]
    assert not any(c[0] == "editMessageReplyMarkup" for c in fake_session.calls), "picker stays so Back still works"


@pytest.mark.asyncio
async def test_the_device_picker_is_disarmed_once_a_device_is_accepted(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(817, "trial:confirm"))
    protocol_id, windows_id = await _ids("L2TP", "Windows")
    await dispatcher.feed_update(bot, make_callback_update(817, f"trial:protocol:{protocol_id}"))
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(817, f"trial:os:{protocol_id}:{windows_id}"))

    first = fake_session.calls[0]
    assert first[0] == "editMessageReplyMarkup"
    assert not (first[1].get("reply_markup") or {}).get("inline_keyboard")


@pytest.mark.asyncio
async def test_a_legacy_platform_button_still_delivers_over_l2tp(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """`trial:platform:<id>` buttons from the previous flow sit in chat
    history and must keep working."""
    await dispatcher.feed_update(bot, make_callback_update(818, "trial:confirm"))
    _, ios_id = await _ids("L2TP", "iOS")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(818, f"trial:platform:{ios_id}"))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert any("Your trial service is ready" in text for text in texts)
    assert len(_pair_attachments(fake_session)) == 1


async def _deliver_openvpn_trial(dispatcher: Any, bot: Any, telegram_id: int) -> None:
    """Runs confirm -> OpenVPN -> iOS, the shortest path that reaches
    _send_trial_credentials."""
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "trial:confirm"))
    protocol_id, ios_id = await _ids("OpenVPN", "iOS")
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"trial:protocol:{protocol_id}"))
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"trial:os:{protocol_id}:{ios_id}"))


@pytest.mark.asyncio
async def test_trial_credentials_missing_password_tells_user_to_contact_support(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_user_password returns None when IBSng has no such user or its
    getUserInfo response carries no stored password. Rendering that
    straight into the message would hand the user "Password: None"."""
    from app.services.ibsng.client import IBSngClient

    async def _no_password(self: Any, *, username: str) -> str | None:
        return None

    monkeypatch.setattr(IBSngClient, "get_user_password", _no_password)
    await _deliver_openvpn_trial(dispatcher, bot, 810)

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert not any("password: <code>none</code>" in c[1]["text"].lower() for c in sent)
    assert any("contact support" in c[1]["text"].lower() for c in sent)


@pytest.mark.asyncio
async def test_trial_credentials_ibsng_failure_tells_user_to_contact_support(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An IBSng failure while re-reading the password must not propagate:
    the account already exists, so the user has to be told something
    actionable instead of being left with a guide and no way to log in."""
    from app.services.ibsng.client import IBSngClient
    from app.services.ibsng.exceptions import IBSngError

    async def _boom(self: Any, *, username: str) -> str | None:
        raise IBSngError("IBSng is down")

    monkeypatch.setattr(IBSngClient, "get_user_password", _boom)
    await _deliver_openvpn_trial(dispatcher, bot, 811)

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("contact support" in c[1]["text"].lower() for c in sent)


@pytest.mark.asyncio
async def test_trial_confirm_allows_second_trial_when_limit_disabled(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, ibsng_server: FakeIBSngServer
) -> None:
    """An admin turning trial_limit_enabled off must let a customer who
    already claimed a trial claim a genuine second one - a real second
    IBSng account and a real second VPNUser row, not an error."""
    from app.db.models.vpn_user import VPNUser
    from app.services.app_config import set_config

    telegram_id = 815
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "trial:confirm"))
    assert ibsng_server.user_count() == 1

    async with async_session_maker() as session:
        await set_config(session, "trial_limit_enabled", "false")

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "trial:confirm"))

    assert ibsng_server.user_count() == 2
    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == telegram_id))).scalars().all()
    assert len(rows) == 2
    assert all(row.is_trial for row in rows)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "already used" not in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_trial_confirm_still_blocked_when_limit_explicitly_enabled(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, ibsng_server: FakeIBSngServer
) -> None:
    """Setting trial_limit_enabled explicitly to "true" (not just leaving
    it unset) must behave identically to the default - one trial per
    customer."""
    from app.services.app_config import set_config

    telegram_id = 816
    async with async_session_maker() as session:
        await set_config(session, "trial_limit_enabled", "true")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "trial:confirm"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "trial:confirm"))

    assert ibsng_server.user_count() == 1
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "already used" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_trial_entry_shows_persian_confirm_for_persian_user(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 820, None)
        await set_language(session, 820, "fa")

    await dispatcher.feed_update(bot, make_callback_update(820, "menu:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "تست رایگان" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_trial_entry_shows_already_used_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=821, ibsng_username="hl.faused1", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await record_seen(session, 821, None)
        await set_language(session, 821, "fa")
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(821, "menu:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "قبلاً" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_trial_ready_credentials_render_in_persian(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 822, None)
        await set_language(session, 822, "fa")

    await dispatcher.feed_update(bot, make_callback_update(822, "trial:confirm"))
    openvpn_id, ios_id = await _ids("OpenVPN", "iOS")
    await dispatcher.feed_update(bot, make_callback_update(822, f"trial:protocol:{openvpn_id}"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(822, f"trial:os:{openvpn_id}:{ios_id}"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    delivery = next(c for c in sent if "سرویس تست شما آماده است" in c[1]["text"])
    assert "یوزرنیم:" in delivery[1]["text"]
    assert "روز از زمان اولین اتصال" in delivery[1]["text"]
    assert "بخش «آموزش»" not in delivery[1]["text"]


@pytest.mark.asyncio
async def test_a_second_tap_on_a_disarmed_picker_sends_nothing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two taps racing each other both reach the handler; Telegram lets
    only one strip the keyboard and answers the other "message is not
    modified". That one must not resend the sequence."""
    from aiogram.exceptions import TelegramBadRequest

    await dispatcher.feed_update(bot, make_callback_update(819, "trial:confirm"))
    protocol_id, windows_id = await _ids("L2TP", "Windows")
    await dispatcher.feed_update(bot, make_callback_update(819, f"trial:protocol:{protocol_id}"))
    fake_session.reset()

    original = fake_session.make_request

    async def _already_disarmed(bot_: Any, method: Any, timeout: int | None = None) -> Any:
        if method.__api_method__ == "editMessageReplyMarkup" and method.reply_markup is None:
            raise TelegramBadRequest(method=method, message="Bad Request: message is not modified")
        return await original(bot_, method, timeout)

    monkeypatch.setattr(fake_session, "make_request", _already_disarmed)
    await dispatcher.feed_update(bot, make_callback_update(819, f"trial:os:{protocol_id}:{windows_id}"))

    assert _outgoing(fake_session) == []
