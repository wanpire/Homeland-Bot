from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update, make_photo_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_admin_cannot_open_tutorial_admin(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(901, "/admintutorials")
    await dispatcher.feed_update(bot, update)

    # A real admin gets a sendMessage with the root admin menu (see
    # test_admin_uploads_a_guide_end_to_end below) - proving denial means
    # proving that specific response never went out, not just that some
    # unrelated substring combination is absent from whatever *did* go
    # out. Confirmed by temporarily removing the admin gate: with the
    # gate removed, this assertion fails and `sent` contains exactly the
    # root-menu sendMessage call below.
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert not any("tutorials & profiles admin" in c[1].get("text", "").lower() for c in sent)
    assert sent == []


@pytest.mark.asyncio
async def test_admin_uploads_a_guide_end_to_end(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))

    async with async_session_maker() as session:
        l2tp_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        ios_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:guide"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:protocol:{l2tp_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:platform:{ios_id}"))
    await dispatcher.feed_update(bot, make_photo_message_update(FAKE_ADMIN_ID, file_id="admin-uploaded-file"))

    async with async_session_maker() as session:
        from app.db.models.tutorial_guide import TutorialGuide

        guide = (
            await session.execute(
                select(TutorialGuide).where(TutorialGuide.platform_id == ios_id, TutorialGuide.protocol_id == l2tp_id)
            )
        ).scalar_one()
    assert guide.media_file_id == "admin-uploaded-file"
    assert guide.media_type == "photo"


@pytest.mark.asyncio
async def test_admin_sets_a_download_link(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id
        ios_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:link"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:link:protocol:{openvpn_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:link:platform:{ios_id}"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "https://apps.apple.com/openvpn-connect"))

    async with async_session_maker() as session:
        link = await get_config(session, "download_link:openvpn:ios")
    assert link == "https://apps.apple.com/openvpn-connect"
