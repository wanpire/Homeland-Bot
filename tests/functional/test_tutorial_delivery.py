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
