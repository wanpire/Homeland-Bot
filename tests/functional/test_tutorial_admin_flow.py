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


@pytest.mark.asyncio
async def test_admin_plain_text_does_not_wipe_an_existing_guide(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    """Guides are media-only from this flow (there is no body_html input),
    so a text message used to be saved as media_file_id=None - silently
    blanking a configured guide while still replying "Saved."."""
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_guide import TutorialGuide
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        l2tp_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        macos_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == "macOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:guide"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:protocol:{l2tp_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:platform:{macos_id}"))
    await dispatcher.feed_update(bot, make_photo_message_update(FAKE_ADMIN_ID, file_id="real-guide-file"))

    # Second run: same target, but the admin sends plain text by mistake.
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:guide"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:protocol:{l2tp_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:platform:{macos_id}"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "oops, I meant to attach a file"))

    async with async_session_maker() as session:
        guide = (
            await session.execute(
                select(TutorialGuide).where(TutorialGuide.platform_id == macos_id, TutorialGuide.protocol_id == l2tp_id)
            )
        ).scalar_one()
    assert guide.media_file_id == "real-guide-file"
    assert guide.media_type == "photo"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert not any(c[1].get("text", "").startswith("✅") for c in sent)
    assert any("photo, document, or video" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_admin_can_save_a_text_only_openvpn_profile(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    """Unlike a guide, a text-only profile is a designed option
    (OpenVpnProfile.text) - plain text must still be accepted here."""
    from sqlalchemy import select as sa_select

    from app.db.models.openvpn_profile import OpenVpnProfile
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:profile"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:profile:protocol:{openvpn_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:profile:platform:none"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "client\nremote vpn.example.com 1194"))

    async with async_session_maker() as session:
        profile = (await session.execute(select(OpenVpnProfile))).scalar_one()
    assert profile.platform_id is None
    assert profile.file_id is None
    assert profile.text == "client\nremote vpn.example.com 1194"


@pytest.mark.asyncio
async def test_admin_empty_profile_message_is_rejected(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.openvpn_profile import OpenVpnProfile
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:profile"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:profile:protocol:{openvpn_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:profile:platform:none"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "   "))

    async with async_session_maker() as session:
        profiles = (await session.execute(select(OpenVpnProfile))).scalars().all()
    assert list(profiles) == []

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("file or" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_every_admin_screen_offers_a_back_button(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    """CLAUDE.md's standing convention: every interactive flow/menu has a
    Back button. Walks the whole flow and checks each screen."""
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol

    def _last_screen_buttons() -> list[str]:
        screens = [c for c in fake_session.calls if c[0] in ("sendMessage", "editMessageText")]
        markup = screens[-1][1].get("reply_markup") or {"inline_keyboard": []}
        return [b["text"] for row in markup["inline_keyboard"] for b in row]

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id

    for update in (
        make_message_update(FAKE_ADMIN_ID, "/admintutorials"),
        make_callback_update(FAKE_ADMIN_ID, "tutadm:guide"),
        make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:protocol:{openvpn_id}"),
        make_callback_update(FAKE_ADMIN_ID, "tutadm:guide:platform:none"),
    ):
        fake_session.reset()
        await dispatcher.feed_update(bot, update)
        assert any("back" in b.lower() for b in _last_screen_buttons())


@pytest.mark.asyncio
async def test_admin_back_buttons_step_back_one_screen(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:guide"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:protocol:{openvpn_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:guide:platform:none"))

    # Content prompt -> platform picker.
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:back:platform"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "pick a platform" in edited[-1][1]["text"].lower()

    # Platform picker -> protocol picker.
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:back:protocol"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "pick a protocol" in edited[-1][1]["text"].lower()

    # Protocol picker -> admin root.
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:back:root"))
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "tutorials & profiles admin" in edited[-1][1]["text"].lower()
