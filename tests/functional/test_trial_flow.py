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


@pytest.mark.asyncio
async def test_trial_openvpn_protocol_skips_platform_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_callback_update(805, "trial:confirm"))
    fake_session.reset()

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(805, f"trial:protocol:{openvpn_id}"))

    sent = [c for c in fake_session.calls if c[0] in ("sendMessage", "editMessageText")]
    assert any("ready" in c[1]["text"].lower() or "hl." in c[1]["text"] for c in sent)


@pytest.mark.asyncio
async def test_trial_l2tp_protocol_shows_platform_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_callback_update(806, "trial:confirm"))
    fake_session.reset()

    async with async_session_maker() as session:
        l2tp_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(806, f"trial:protocol:{l2tp_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("ios" in b.lower() for b in buttons)
    assert any("android" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_trial_platform_pick_delivers_and_sends_credentials(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_callback_update(807, "trial:confirm"))

    async with async_session_maker() as session:
        l2tp_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        ios_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(807, f"trial:protocol:{l2tp_id}"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(807, f"trial:platform:{ios_id}"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("hl." in c[1]["text"] and "24" in c[1]["text"] for c in sent)


async def _deliver_openvpn_trial(dispatcher: Any, bot: Any, telegram_id: int) -> None:
    """Runs confirm -> OpenVPN, the shortest path that reaches
    _send_trial_credentials."""
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "trial:confirm"))
    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"trial:protocol:{openvpn_id}"))


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
