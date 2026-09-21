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


async def _seed_guide(*, protocol_id: int, platform_id: int | None, body: str) -> None:
    from app.db.models.tutorial_guide import TutorialGuide

    async with async_session_maker() as session:
        session.add(TutorialGuide(protocol_id=protocol_id, platform_id=platform_id, body_html=body))
        await session.commit()


async def _seed_link(*, protocol_label: str, platform_label: str | None, url: str) -> None:
    from app.services.app_config import set_config
    from app.services.tutorial_delivery import download_link_key

    async with async_session_maker() as session:
        await set_config(
            session, download_link_key(protocol_label=protocol_label, platform_label=platform_label), url
        )


async def _seed_profile(*, platform_id: int | None, name: str = "homeland.ovpn") -> None:
    from app.services.tutorials import upsert_profile

    async with async_session_maker() as session:
        await upsert_profile(
            session, platform_id=platform_id, name=name, file_id="profile-file-id", file_type="document", text=None
        )


def _screens(fake_session: FakeBotSession) -> list[tuple[str, dict[str, Any]]]:
    return [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]


def _buttons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for row in (payload.get("reply_markup") or {"inline_keyboard": []})["inline_keyboard"] for b in row]


def _all_text(fake_session: FakeBotSession) -> str:
    return " ".join((c[1].get("text") or c[1].get("caption") or "") for c in fake_session.calls).lower()


@pytest.mark.asyncio
async def test_entry_lists_the_active_protocols(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(901, "menu:tutorials"))

    payload = _screens(fake_session)[-1][1]
    labels = {b["text"]: b["callback_data"] for b in _buttons(payload)}
    assert "OpenVPN" in labels and "L2TP" in labels
    assert any("back" in text.lower() for text in labels)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol_label", ["OpenVPN", "L2TP"])
async def test_every_protocol_asks_for_the_device(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, protocol_label: str
) -> None:
    """OpenVPN used to skip this step; it now behaves exactly like L2TP."""
    protocol_id = await _protocol_id(protocol_label)
    ios_id = await _platform_id("iOS")

    await dispatcher.feed_update(bot, make_callback_update(902, f"tut:protocol:{protocol_id}"))

    payload = _screens(fake_session)[-1][1]
    labels = {b["text"]: b.get("callback_data") for b in _buttons(payload)}
    assert labels["iOS"] == f"tut:platform:{protocol_id}:{ios_id}"
    assert "Android" in labels and "Windows" in labels and "macOS" in labels
    assert any("back" in text.lower() for text in labels)


@pytest.mark.asyncio
async def test_platform_pick_sends_the_guide(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    l2tp_id = await _protocol_id("L2TP")
    ios_id = await _platform_id("iOS")
    await _seed_guide(protocol_id=l2tp_id, platform_id=ios_id, body="L2TP on iOS: step one")

    await dispatcher.feed_update(bot, make_callback_update(903, f"tut:platform:{l2tp_id}:{ios_id}"))

    assert "l2tp on ios: step one" in _all_text(fake_session)


@pytest.mark.asyncio
async def test_openvpn_falls_back_to_the_generic_guide(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """An admin may upload one generic OpenVPN guide rather than four
    identical per-device copies; asking for a device must not hide it."""
    openvpn_id = await _protocol_id("OpenVPN")
    windows_id = await _platform_id("Windows")
    await _seed_guide(protocol_id=openvpn_id, platform_id=None, body="Generic OpenVPN instructions")

    await dispatcher.feed_update(bot, make_callback_update(904, f"tut:platform:{openvpn_id}:{windows_id}"))

    assert "generic openvpn instructions" in _all_text(fake_session)


@pytest.mark.asyncio
async def test_device_specific_guide_wins_over_the_generic_one(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    openvpn_id = await _protocol_id("OpenVPN")
    windows_id = await _platform_id("Windows")
    await _seed_guide(protocol_id=openvpn_id, platform_id=None, body="Generic OpenVPN instructions")
    await _seed_guide(protocol_id=openvpn_id, platform_id=windows_id, body="Windows specific instructions")

    await dispatcher.feed_update(bot, make_callback_update(905, f"tut:platform:{openvpn_id}:{windows_id}"))

    text = _all_text(fake_session)
    assert "windows specific instructions" in text
    assert "generic openvpn instructions" not in text


@pytest.mark.asyncio
async def test_link_and_profile_are_buttons_not_automatic_sends(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    openvpn_id = await _protocol_id("OpenVPN")
    ios_id = await _platform_id("iOS")
    await _seed_guide(protocol_id=openvpn_id, platform_id=ios_id, body="OpenVPN iOS guide")
    await _seed_link(protocol_label="OpenVPN", platform_label="iOS", url="https://apps.apple.com/openvpn")
    await _seed_profile(platform_id=ios_id)

    await dispatcher.feed_update(bot, make_callback_update(906, f"tut:platform:{openvpn_id}:{ios_id}"))

    text = _all_text(fake_session)
    assert "openvpn ios guide" in text
    assert "apps.apple.com" not in text, "the link must wait behind its button"
    assert not any(c[0] == "sendDocument" for c in fake_session.calls), "the profile must wait behind its button"

    labels = {b["text"]: b.get("callback_data") for b in _buttons(_screens(fake_session)[-1][1])}
    assert labels["📥 Download Link"] == f"tut:link:{openvpn_id}:{ios_id}"
    assert labels["📄 OpenVPN Profile"] == f"tut:profile:{openvpn_id}:{ios_id}"


@pytest.mark.asyncio
async def test_download_link_button_sends_the_link(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    l2tp_id = await _protocol_id("L2TP")
    ios_id = await _platform_id("iOS")
    await _seed_link(protocol_label="L2TP", platform_label="iOS", url="https://example.com/l2tp-ios")

    await dispatcher.feed_update(bot, make_callback_update(907, f"tut:link:{l2tp_id}:{ios_id}"))

    assert "https://example.com/l2tp-ios" in " ".join((c[1].get("text") or "") for c in fake_session.calls)


@pytest.mark.asyncio
async def test_profile_button_sends_the_profile(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    openvpn_id = await _protocol_id("OpenVPN")
    ios_id = await _platform_id("iOS")
    await _seed_profile(platform_id=ios_id)

    await dispatcher.feed_update(bot, make_callback_update(908, f"tut:profile:{openvpn_id}:{ios_id}"))

    assert any(c[0] == "sendDocument" and c[1].get("document") == "profile-file-id" for c in fake_session.calls)


@pytest.mark.asyncio
async def test_buttons_are_hidden_when_nothing_is_uploaded(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A button that answers "nothing here" is worse than no button."""
    l2tp_id = await _protocol_id("L2TP")
    macos_id = await _platform_id("macOS")

    await dispatcher.feed_update(bot, make_callback_update(909, f"tut:platform:{l2tp_id}:{macos_id}"))

    labels = [b["text"] for b in _buttons(_screens(fake_session)[-1][1])]
    assert not any("download" in label.lower() for label in labels)
    assert not any("profile" in label.lower() for label in labels)
    assert labels, "there must still be a way onward"


@pytest.mark.asyncio
async def test_profile_button_is_not_offered_for_l2tp(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A stored profile is an OpenVPN artefact - offering it under L2TP
    would hand the user a file their client cannot use."""
    l2tp_id = await _protocol_id("L2TP")
    ios_id = await _platform_id("iOS")
    await _seed_profile(platform_id=ios_id)
    await _seed_link(protocol_label="L2TP", platform_label="iOS", url="https://example.com/l2tp-ios")

    await dispatcher.feed_update(bot, make_callback_update(910, f"tut:platform:{l2tp_id}:{ios_id}"))

    labels = [b["text"] for b in _buttons(_screens(fake_session)[-1][1])]
    assert any("download" in label.lower() for label in labels)
    assert not any("profile" in label.lower() for label in labels)


@pytest.mark.asyncio
async def test_android_with_l2tp_is_refused_but_not_a_dead_end(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    l2tp_id = await _protocol_id("L2TP")
    android_id = await _platform_id("Android")

    await dispatcher.feed_update(bot, make_callback_update(911, f"tut:platform:{l2tp_id}:{android_id}"))

    text = _all_text(fake_session)
    assert "android" in text
    assert "not ready" not in text, "the compatibility notice replaces delivery, it doesn't accompany it"
    assert _buttons(_screens(fake_session)[-1][1]), "a refused combination must still offer a way onward"


@pytest.mark.asyncio
async def test_missing_guide_says_so_and_still_offers_the_extras(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    openvpn_id = await _protocol_id("OpenVPN")
    ios_id = await _platform_id("iOS")
    await _seed_link(protocol_label="OpenVPN", platform_label="iOS", url="https://apps.apple.com/openvpn")

    await dispatcher.feed_update(bot, make_callback_update(912, f"tut:platform:{openvpn_id}:{ios_id}"))

    assert "not ready" in _all_text(fake_session)
    labels = [b["text"] for b in _buttons(_screens(fake_session)[-1][1])]
    assert any("download" in label.lower() for label in labels)


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["tut:protocol:999999", "tut:platform:999999:1", "tut:link:999999:1", "tut:profile:999999:1"])
async def test_stale_keyboards_return_to_the_protocol_list(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(913, data))

    labels = [b["text"] for b in _buttons(_screens(fake_session)[-1][1])]
    assert "OpenVPN" in labels


@pytest.mark.asyncio
async def test_empty_catalog_shows_a_clear_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    async with async_session_maker() as session:
        for protocol in (await session.execute(select(TutorialProtocol))).scalars().all():
            protocol.is_active = False
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(914, "menu:tutorials"))

    payload = _screens(fake_session)[-1][1]
    assert "support" in payload["text"].lower() or "پشتیبانی" in payload["text"]
    assert any("back" in b["text"].lower() for b in _buttons(payload))


@pytest.mark.asyncio
async def test_entry_works_when_tapped_under_a_campaign_photo(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    photo = make_photo_message(915, file_id="campaign-photo")
    await dispatcher.feed_update(bot, make_callback_update(915, "menu:tutorials", anchor_message=photo))

    assert [c for c in fake_session.calls if c[0] == "editMessageText"] == []
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert sent and _buttons(sent[-1][1])
