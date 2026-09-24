from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer
from tests.handover_helpers import latest_device_picker, pair_attachments


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
async def test_trial_confirm_creates_account_then_shows_the_device_picker_first(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
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
    assert "device" in edited[0][1]["text"].lower()
    buttons = {b["text"]: b["callback_data"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row}
    assert {"iOS", "Android", "Windows", "macOS"} <= set(buttons)
    assert buttons["iOS"].startswith(f"ho:t:{vpn_user.id}:os:")
    assert not any("l2tp" in b.lower() or "openvpn" in b.lower() for b in buttons), "protocol comes second"
    assert "menu:root" in buttons.values()


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


async def _trial_id(telegram_id: int) -> int:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        return (await session.execute(select(VPNUser.id).where(VPNUser.telegram_id == telegram_id))).scalar_one()


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


async def _pick_device(dispatcher: Any, bot: Any, telegram_id: int, platform: str) -> None:
    """confirm -> device, stopping at the protocol step (or, on Android,
    at the end of the sequence)."""
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "trial:confirm"))
    _, platform_id = await _ids("OpenVPN", platform)
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, f"ho:t:{await _trial_id(telegram_id)}:os:{platform_id}")
    )


def _protocol_cb(trial_id: int, platform_id: int, protocol_id: int) -> str:
    return f"ho:t:{trial_id}:pr:{platform_id}:{protocol_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["iOS", "Windows", "macOS"])
async def test_a_device_with_a_choice_asks_for_the_protocol_second(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, platform: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(805, "trial:confirm"))
    _, platform_id = await _ids("OpenVPN", platform)
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(805, f"ho:t:{await _trial_id(805)}:os:{platform_id}"))

    assert _outgoing(fake_session) == [], "no credentials or files before the protocol is chosen"
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "protocol" in edited[0][1]["text"].lower()
    buttons = {b["text"]: b["callback_data"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row}
    openvpn_id, _ = await _ids("OpenVPN")
    assert buttons["OpenVPN"] == _protocol_cb(await _trial_id(805), platform_id, openvpn_id)
    assert "L2TP" in buttons
    assert buttons["⬅️ Back"] == f"ho:t:{await _trial_id(805)}:back"


@pytest.mark.asyncio
async def test_android_skips_the_protocol_step_and_delivers_over_openvpn(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Android has no L2TP, so there is no choice to offer: the device tap
    goes straight to credentials and the OpenVPN setup."""
    await _seed_openvpn_material()
    await dispatcher.feed_update(bot, make_callback_update(823, "trial:confirm"))
    _, android_id = await _ids("OpenVPN", "Android")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(823, f"ho:t:{await _trial_id(823)}:os:{android_id}"))

    assert not any(c[0] == "editMessageText" for c in fake_session.calls), "no protocol picker"
    assert not any(":pr:" in str(c[1]) for c in fake_session.calls)
    out = _outgoing(fake_session)
    assert [c[0] for c in out] == ["sendMessage", "sendDocument", "sendMessage"], "credentials, config, link"
    assert "Your trial service is ready" in out[0][1]["text"]
    assert _OVPN_LINKS["Android"] in out[2][1]["text"]
    assert len(pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_the_back_button_returns_from_protocol_to_device(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _pick_device(dispatcher, bot, 824, "iOS")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(824, f"ho:t:{await _trial_id(824)}:back"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    callbacks = [b["callback_data"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any(":os:" in cb for cb in callbacks)
    assert _outgoing(fake_session) == []


@pytest.mark.asyncio
async def test_openvpn_sends_credentials_then_that_devices_setup_only(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_openvpn_material()
    await _pick_device(dispatcher, bot, 806, "Windows")
    openvpn_id, windows_id = await _ids("OpenVPN", "Windows")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(806, _protocol_cb(await _trial_id(806), windows_id, openvpn_id)))

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
    assert len(pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_the_final_pair_lands_on_the_last_message_of_the_sequence(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_openvpn_material()
    await _pick_device(dispatcher, bot, 812, "iOS")
    openvpn_id, ios_id = await _ids("OpenVPN", "iOS")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(812, _protocol_cb(await _trial_id(812), ios_id, openvpn_id)))

    calls = [c for c in fake_session.calls if c[0] != "answerCallbackQuery"]
    last_send = max(i for i, c in enumerate(calls) if c[0] in ("sendMessage", "sendDocument"))
    assert _OVPN_LINKS["iOS"] in calls[last_send][1]["text"], "the link is the last thing sent"
    assert calls[-1][0] == "editMessageReplyMarkup", "the pair is attached after it"
    assert pair_attachments(fake_session) == [calls[-1][1]]


@pytest.mark.asyncio
async def test_with_no_setup_material_the_pair_goes_on_the_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """L2TP on macOS uses the built-in client: nothing may be configured
    beyond the credentials, and the pair must still appear."""
    await _pick_device(dispatcher, bot, 813, "macOS")
    l2tp_id, macos_id = await _ids("L2TP", "macOS")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(813, _protocol_cb(await _trial_id(813), macos_id, l2tp_id)))

    out = _outgoing(fake_session)
    assert len(out) == 1 and "Your trial service is ready" in out[0][1]["text"]
    assert len(pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_l2tp_sends_that_devices_guide_after_the_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.tutorials import upsert_guide

    l2tp_id, ios_id = await _ids("L2TP", "iOS")
    async with async_session_maker() as session:
        guide = await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id=None, media_type=None)
        guide.body_html = "iOS L2TP steps"
        await session.commit()

    await _pick_device(dispatcher, bot, 807, "iOS")
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(807, _protocol_cb(await _trial_id(807), ios_id, l2tp_id)))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert len(texts) == 2
    assert "Your trial service is ready" in texts[0]
    assert "<b>Plan:</b> Trial" in texts[0]
    assert "1 day from first connection" in texts[0]
    assert texts[1] == "iOS L2TP steps"
    assert len(pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_a_forged_android_l2tp_tap_is_refused_before_any_credentials(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """The picker never offers it, but callback data is just a string: the
    shared gate still refuses before anything irreversible goes out."""
    await dispatcher.feed_update(bot, make_callback_update(814, "trial:confirm"))
    l2tp_id, android_id = await _ids("L2TP", "Android")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(814, _protocol_cb(await _trial_id(814), android_id, l2tp_id)))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert len(texts) == 1 and "OpenVPN" in texts[0]
    assert not any(c[0] == "editMessageReplyMarkup" for c in fake_session.calls), "picker stays so Back still works"


@pytest.mark.asyncio
async def test_another_users_trial_cannot_be_claimed(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _pick_device(dispatcher, bot, 825, "iOS")
    openvpn_id, ios_id = await _ids("OpenVPN", "iOS")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(826, _protocol_cb(await _trial_id(825), ios_id, openvpn_id)))

    assert _outgoing(fake_session) == []


@pytest.mark.asyncio
async def test_the_picker_is_disarmed_once_a_protocol_is_accepted(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _pick_device(dispatcher, bot, 817, "Windows")
    l2tp_id, windows_id = await _ids("L2TP", "Windows")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(817, _protocol_cb(await _trial_id(817), windows_id, l2tp_id)))

    first = fake_session.calls[0]
    assert first[0] == "editMessageReplyMarkup"
    assert not (first[1].get("reply_markup") or {}).get("inline_keyboard")


@pytest.mark.asyncio
async def test_a_second_tap_on_a_disarmed_picker_sends_nothing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two taps racing each other both reach the handler; Telegram lets
    only one strip the keyboard and answers the other "message is not
    modified". That one must not resend the sequence."""
    from aiogram.exceptions import TelegramBadRequest

    await _pick_device(dispatcher, bot, 819, "Windows")
    l2tp_id, windows_id = await _ids("L2TP", "Windows")
    fake_session.reset()

    original = fake_session.make_request

    async def _already_disarmed(bot_: Any, method: Any, timeout: int | None = None) -> Any:
        if method.__api_method__ == "editMessageReplyMarkup" and method.reply_markup is None:
            raise TelegramBadRequest(method=method, message="Bad Request: message is not modified")
        return await original(bot_, method, timeout)

    monkeypatch.setattr(fake_session, "make_request", _already_disarmed)
    await dispatcher.feed_update(bot, make_callback_update(819, _protocol_cb(await _trial_id(819), windows_id, l2tp_id)))

    assert _outgoing(fake_session) == []


@pytest.mark.asyncio
async def test_trial_runs_through_the_shared_handover(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One implementation of the sequence: the trial hands off to the same
    function purchase and renewal use (see test_handover_paid.py)."""
    import app.bot.handlers.handover as handover_handler

    seen: list[Any] = []

    async def _spy(bot_: Any, telegram_id: int, account: Any, **kwargs: Any) -> bool:
        seen.append(account)
        return True

    monkeypatch.setattr(handover_handler, "deliver_handover", _spy)
    await _pick_device(dispatcher, bot, 827, "Android")

    assert len(seen) == 1 and seen[0].kind == "trial"


# --- Legacy callbacks from the previous protocol-first flow -------------


@pytest.mark.asyncio
async def test_a_legacy_os_button_still_delivers(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(828, "trial:confirm"))
    l2tp_id, ios_id = await _ids("L2TP", "iOS")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(828, f"trial:os:{l2tp_id}:{ios_id}"))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert any("Your trial service is ready" in text for text in texts)
    assert len(pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
async def test_a_legacy_android_l2tp_button_is_still_refused(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(829, "trial:confirm"))
    l2tp_id, android_id = await _ids("L2TP", "Android")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(829, f"trial:os:{l2tp_id}:{android_id}"))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert len(texts) == 1 and "OpenVPN" in texts[0]


@pytest.mark.asyncio
async def test_a_legacy_platform_button_still_delivers_over_l2tp(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """`trial:platform:<id>` buttons from the oldest flow sit in chat
    history and must keep working."""
    await dispatcher.feed_update(bot, make_callback_update(818, "trial:confirm"))
    _, ios_id = await _ids("L2TP", "iOS")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(818, f"trial:platform:{ios_id}"))

    texts = [c[1]["text"] for c in _outgoing(fake_session)]
    assert any("Your trial service is ready" in text for text in texts)
    assert len(pair_attachments(fake_session)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", ["trial:protocol:{p}", "trial:back_to_protocol"])
async def test_a_legacy_protocol_button_opens_the_device_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, legacy: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(830, "trial:confirm"))
    openvpn_id, _ = await _ids("OpenVPN")
    fake_session.reset()

    await dispatcher.feed_update(bot, make_callback_update(830, legacy.format(p=openvpn_id)))

    assert _outgoing(fake_session) == []
    picker = latest_device_picker(fake_session, 830)
    assert picker["iOS"].startswith(f"ho:t:{await _trial_id(830)}:os:")


async def _deliver_openvpn_trial(dispatcher: Any, bot: Any, telegram_id: int) -> None:
    """Runs confirm -> iOS -> OpenVPN, the shortest path with a choice."""
    await _pick_device(dispatcher, bot, telegram_id, "iOS")
    openvpn_id, ios_id = await _ids("OpenVPN", "iOS")
    await dispatcher.feed_update(
        bot, make_callback_update(telegram_id, _protocol_cb(await _trial_id(telegram_id), ios_id, openvpn_id))
    )


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
    from app.services.bot_users import record_seen, set_language

    async with async_session_maker() as session:
        await record_seen(session, 822, None)
        await set_language(session, 822, "fa")

    await _pick_device(dispatcher, bot, 822, "iOS")
    openvpn_id, ios_id = await _ids("OpenVPN", "iOS")
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(822, _protocol_cb(await _trial_id(822), ios_id, openvpn_id)))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    delivery = next(c for c in sent if "سرویس تست شما آماده است" in c[1]["text"])
    assert "یوزرنیم:" in delivery[1]["text"]
    assert "روز از زمان اولین اتصال" in delivery[1]["text"]
    assert "بخش «آموزش»" not in delivery[1]["text"]
