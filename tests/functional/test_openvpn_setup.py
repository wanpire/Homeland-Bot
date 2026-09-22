"""The post-handover OpenVPN setup step.

Replaces a single message that listed every platform's download link at
once, and the "this guide is not ready" placeholder that followed the
config file in the middle of a successful handover.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession

_LINKS = {
    "iOS": "https://apps.apple.com/openvpn",
    "Android": "https://play.google.com/openvpn",
    "Windows": "https://openvpn.net/windows",
    "macOS": "https://openvpn.net/macos",
}


async def _platform_id(label: str) -> int:
    async with async_session_maker() as session:
        return (
            await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == label))
        ).scalar_one().id


async def _seed_links(*, only: str | None = None) -> None:
    from app.services.app_config import set_config
    from app.services.tutorial_delivery import download_link_key

    async with async_session_maker() as session:
        for label, url in _LINKS.items():
            if only is not None and label != only:
                continue
            await set_config(session, download_link_key(protocol_label="OpenVPN", platform_label=label), url)


async def _seed_profile() -> None:
    from app.services.tutorials import upsert_profile

    async with async_session_maker() as session:
        await upsert_profile(
            session, platform_id=None, name="ir.alonet.ovpn",
            file_id="ovpn-file-id", file_type="document", text=None,
        )


def _texts(fake_session: FakeBotSession) -> str:
    return " ".join((c[1].get("text") or c[1].get("caption") or "") for c in fake_session.calls)


def _buttons(payload: dict[str, Any]) -> dict[str, Any]:
    return {b["text"]: b.get("callback_data") for row in payload["reply_markup"]["inline_keyboard"] for b in row}


@pytest.mark.asyncio
async def test_setup_step_sends_the_profile_then_a_platform_prompt(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.openvpn_setup import send_openvpn_setup

    await _seed_profile()
    await _seed_links()

    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4001, session, lang="en")

    kinds = [c[0] for c in fake_session.calls]
    assert "sendDocument" in kinds, "the .ovpn config still goes out unchanged"
    assert kinds.index("sendDocument") < kinds.index("sendMessage"), "config first, then the prompt"

    prompt = [c for c in fake_session.calls if c[0] == "sendMessage"][-1][1]
    assert "Download OpenVPN Connect" in prompt["text"]
    labels = _buttons(prompt)
    assert labels["iOS"] == f"ovpn:link:{await _platform_id('iOS')}"
    assert {"iOS", "Android", "Windows", "macOS"} <= set(labels)


@pytest.mark.asyncio
async def test_no_links_are_sent_until_a_platform_is_picked(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """The whole point of the change: four links in one message is what
    this replaced."""
    from app.services.openvpn_setup import send_openvpn_setup

    await _seed_links()
    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4002, session, lang="en")

    text = _texts(fake_session)
    for url in _LINKS.values():
        assert url not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_LINKS))
async def test_picking_a_platform_sends_only_that_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, label: str
) -> None:
    await _seed_links()
    platform_id = await _platform_id(label)

    await dispatcher.feed_update(bot, make_callback_update(4003, f"ovpn:link:{platform_id}"))

    text = _texts(fake_session)
    assert _LINKS[label] in text
    for other, url in _LINKS.items():
        if other != label:
            assert url not in text


@pytest.mark.asyncio
async def test_a_platform_without_a_link_answers_with_an_alert(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _seed_links(only="iOS")
    platform_id = await _platform_id("macOS")

    await dispatcher.feed_update(bot, make_callback_update(4004, f"ovpn:link:{platform_id}"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True
    assert "openvpn.net/macos" not in _texts(fake_session)


@pytest.mark.asyncio
async def test_a_generic_link_covers_a_platform_without_its_own(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """The admin's "Generic (any platform)" entry must still be honoured."""
    from app.services.app_config import set_config
    from app.services.tutorial_delivery import download_link_key

    async with async_session_maker() as session:
        await set_config(
            session, download_link_key(protocol_label="OpenVPN", platform_label=None), "https://openvpn.net/any"
        )
    platform_id = await _platform_id("Windows")

    await dispatcher.feed_update(bot, make_callback_update(4005, f"ovpn:link:{platform_id}"))

    assert "https://openvpn.net/any" in _texts(fake_session)


@pytest.mark.asyncio
async def test_the_setup_step_never_says_a_guide_is_not_ready(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """No OpenVPN guide has ever been uploaded, and this step looks none
    up - the placeholder cannot fire here."""
    from app.services.openvpn_setup import send_openvpn_setup

    await _seed_profile()
    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4006, session, lang="en")

    assert "not ready" not in _texts(fake_session).lower()


@pytest.mark.asyncio
async def test_persian_prompt(bot: Any, fake_session: FakeBotSession, seeded_catalog: dict) -> None:
    from app.services.openvpn_setup import send_openvpn_setup

    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4007, session, lang="fa")

    prompt = [c for c in fake_session.calls if c[0] == "sendMessage"][-1][1]
    assert "دانلود OpenVPN Connect" in prompt["text"]
    # Platform names are proper nouns and stay untranslated.
    assert {"iOS", "Android", "Windows", "macOS"} <= set(_buttons(prompt))


@pytest.mark.asyncio
async def test_a_missing_profile_still_reaches_the_prompt(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """The account is already provisioned by the time this runs, so no
    absent content may make the handover look failed."""
    from app.services.openvpn_setup import send_openvpn_setup

    async with async_session_maker() as session:
        await send_openvpn_setup(bot, 4008, session, lang="en")

    assert any(c[0] == "sendMessage" for c in fake_session.calls)
