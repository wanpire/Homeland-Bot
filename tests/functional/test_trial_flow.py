from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession


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
