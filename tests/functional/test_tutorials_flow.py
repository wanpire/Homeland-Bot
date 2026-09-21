from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.session import async_session_maker
from tests.factories import make_callback_update, make_photo_message
from tests.fakes.fake_bot_session import FakeBotSession


async def _protocol_id(label: str) -> int:
    async with async_session_maker() as session:
        return (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == label))).scalar_one().id


async def _platform_id(label: str) -> int:
    async with async_session_maker() as session:
        return (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == label))).scalar_one().id


def _screens(fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    return [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]


def _buttons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for row in (payload.get("reply_markup") or {"inline_keyboard": []})["inline_keyboard"] for b in row]


@pytest.mark.asyncio
async def test_entry_lists_the_active_protocols(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(901, "menu:tutorials"))

    payload = _screens(fake_session)[-1][1]
    assert "tutorial" in payload["text"].lower() or "آموزش" in payload["text"]
    labels = {b["text"]: b["callback_data"] for b in _buttons(payload)}
    assert "OpenVPN" in labels and "L2TP" in labels
    assert any("back" in text.lower() for text in labels)


@pytest.mark.asyncio
async def test_openvpn_skips_the_device_question_and_delivers(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """OpenVPN's guide is stored platform-independently, so asking which
    device would show everyone the same page - same shortcut the Trial
    and My Services flows take."""
    openvpn_id = await _protocol_id("OpenVPN")

    await dispatcher.feed_update(bot, make_callback_update(902, f"tut:protocol:{openvpn_id}"))

    texts = " ".join((c[1].get("text") or "") for c in _screens(fake_session)).lower()
    assert "which device" not in texts, "OpenVPN must not ask for a platform"
    # Nothing is uploaded in the test database, so deliver_setup reports
    # the guide isn't ready - the point is that delivery was attempted.
    assert "not ready" in texts
    last = _screens(fake_session)[-1][1]
    assert any("back" in b["text"].lower() or "another" in b["text"].lower() for b in _buttons(last))


@pytest.mark.asyncio
async def test_l2tp_asks_for_the_device_then_delivers(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    l2tp_id = await _protocol_id("L2TP")
    ios_id = await _platform_id("iOS")

    await dispatcher.feed_update(bot, make_callback_update(903, f"tut:protocol:{l2tp_id}"))
    payload = _screens(fake_session)[-1][1]
    labels = {b["text"]: b.get("callback_data") for b in _buttons(payload)}
    assert labels["iOS"] == f"tut:platform:{l2tp_id}:{ios_id}"
    assert any("back" in text.lower() for text in labels)

    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(903, f"tut:platform:{l2tp_id}:{ios_id}"))
    texts = " ".join((c[1].get("text") or "") for c in _screens(fake_session)).lower()
    assert "not ready" in texts  # delivery attempted; nothing uploaded in tests
    last = _screens(fake_session)[-1][1]
    assert _buttons(last), "the closing screen must offer a way onward"


@pytest.mark.asyncio
async def test_android_with_l2tp_is_refused_but_not_a_dead_end(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Android 12+ dropped its built-in L2TP client. The user still needs
    a way back, which the old flow's bare notice never gave them."""
    l2tp_id = await _protocol_id("L2TP")
    android_id = await _platform_id("Android")

    await dispatcher.feed_update(bot, make_callback_update(904, f"tut:platform:{l2tp_id}:{android_id}"))

    texts = " ".join((c[1].get("text") or "") for c in _screens(fake_session)).lower()
    assert "android" in texts
    assert "not ready" not in texts, "the compatibility notice replaces delivery, it doesn't accompany it"
    last = _screens(fake_session)[-1][1]
    assert _buttons(last), "a refused combination must still offer a way onward"


@pytest.mark.asyncio
async def test_unknown_protocol_id_returns_to_the_protocol_list(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A stale keyboard from before a protocol was deactivated must not
    crash deliver_setup on a missing row."""
    await dispatcher.feed_update(bot, make_callback_update(905, "tut:protocol:999999"))

    labels = [b["text"] for b in _buttons(_screens(fake_session)[-1][1])]
    assert "OpenVPN" in labels


@pytest.mark.asyncio
async def test_unknown_platform_pair_returns_to_the_protocol_list(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(906, "tut:platform:999999:1"))

    labels = [b["text"] for b in _buttons(_screens(fake_session)[-1][1])]
    assert "OpenVPN" in labels


@pytest.mark.asyncio
async def test_empty_catalog_shows_a_clear_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Nothing uploaded yet must read as "not available", never as a blank
    screen with no buttons."""
    async with async_session_maker() as session:
        for protocol in (await session.execute(select(TutorialProtocol))).scalars().all():
            protocol.is_active = False
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(907, "menu:tutorials"))

    payload = _screens(fake_session)[-1][1]
    assert "support" in payload["text"].lower() or "پشتیبانی" in payload["text"]
    assert any("back" in b["text"].lower() for b in _buttons(payload))


@pytest.mark.asyncio
async def test_entry_works_when_tapped_under_a_campaign_photo(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """An Ad Campaign button pointing at Tutorials arrives attached to a
    photo, which Telegram refuses to edit into a text screen."""
    photo = make_photo_message(908, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(908, "menu:tutorials", anchor_message=photo))

    assert [c for c in fake_session.calls if c[0] == "editMessageText"] == []
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert sent and _buttons(sent[-1][1])
