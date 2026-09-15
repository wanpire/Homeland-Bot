from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_deliver_setup_blocks_android_l2tp(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup

    async with async_session_maker() as session:
        android_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "Android"))).scalar_one().id
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        delivered, guide_message_id = await deliver_setup(bot, 701, session, protocol_id=l2tp_id, platform_id=android_id)

    assert delivered is False
    assert guide_message_id is None
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("android" in c[1]["text"].lower() or "l2tp" in c[1]["text"].lower() for c in sent)


@pytest.mark.asyncio
async def test_deliver_setup_sends_guide_and_credentials_placeholder_when_configured(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup
    from app.services.tutorials import upsert_guide

    async with async_session_maker() as session:
        ios_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id=None, media_type=None)

    async with async_session_maker() as session:
        delivered, guide_message_id = await deliver_setup(bot, 702, session, protocol_id=l2tp_id, platform_id=ios_id)

    assert delivered is True
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) >= 1


@pytest.mark.asyncio
async def test_deliver_setup_falls_back_gracefully_when_no_guide_configured(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup

    async with async_session_maker() as session:
        macos_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "macOS"))).scalar_one().id
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        delivered, _ = await deliver_setup(bot, 703, session, protocol_id=l2tp_id, platform_id=macos_id)

    assert delivered is True
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("not ready" in c[1]["text"].lower() for c in sent)


@pytest.mark.asyncio
async def test_deliver_setup_replays_the_configured_guide_file(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup
    from app.services.tutorials import upsert_guide

    async with async_session_maker() as session:
        ios_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id="guide-file-123", media_type="photo")

    async with async_session_maker() as session:
        delivered, guide_message_id = await deliver_setup(bot, 704, session, protocol_id=l2tp_id, platform_id=ios_id)

    assert delivered is True
    assert guide_message_id is not None
    sent_photos = [c for c in fake_session.calls if c[0] == "sendPhoto"]
    assert any(c[1]["photo"] == "guide-file-123" for c in sent_photos)


@pytest.mark.asyncio
async def test_deliver_setup_replays_the_matched_openvpn_profile_file(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup
    from app.services.tutorials import upsert_profile

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id
        await upsert_profile(session, platform_id=None, name="Test Profile", file_id="profile-file-456", file_type="document", text=None)

    async with async_session_maker() as session:
        delivered, _ = await deliver_setup(bot, 705, session, protocol_id=openvpn_id, platform_id=None)

    assert delivered is True
    sent_documents = [c for c in fake_session.calls if c[0] == "sendDocument"]
    assert any(c[1]["document"] == "profile-file-456" for c in sent_documents)


@pytest.mark.asyncio
async def test_deliver_setup_shows_the_generic_download_link_with_no_platform(bot: Any, fake_session: FakeBotSession) -> None:
    """The admin flow's "Generic (any platform)" option writes
    `download_link:{protocol}:any`. deliver_setup used to read only real
    platform labels, so that key was written and never shown to anyone."""
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.app_config import set_config
    from app.services.tutorial_delivery import deliver_setup

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id
        await set_config(session, "download_link:openvpn:any", "https://openvpn.net/client/")

    async with async_session_maker() as session:
        delivered, _ = await deliver_setup(bot, 706, session, protocol_id=openvpn_id, platform_id=None)

    assert delivered is True
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("https://openvpn.net/client/" in c[1]["text"] for c in sent)


@pytest.mark.asyncio
async def test_deliver_setup_falls_back_to_the_generic_link_for_a_specific_platform(
    bot: Any, fake_session: FakeBotSession
) -> None:
    """Same key, the other branch: a platform with no link of its own
    still gets the generic one."""
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.app_config import set_config
    from app.services.tutorial_delivery import deliver_setup

    async with async_session_maker() as session:
        windows_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "Windows"))).scalar_one().id
        openvpn_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id
        await set_config(session, "download_link:openvpn:any", "https://openvpn.net/client/")

    async with async_session_maker() as session:
        delivered, _ = await deliver_setup(bot, 707, session, protocol_id=openvpn_id, platform_id=windows_id)

    assert delivered is True
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("https://openvpn.net/client/" in c[1]["text"] for c in sent)
