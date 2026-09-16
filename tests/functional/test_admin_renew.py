from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_admin_cannot_start_renew_flow(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "adm:users:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_admin_renews_unknown_ibsng_username_shows_not_found(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    scroll_plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ghost-user"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renew:plan:{scroll_plan['id']}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_admin_renews_bot_created_account_updates_row_and_notifies_user(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.catalog import get_plan
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    scroll_plans = [p for p in seeded_catalog["plans"] if p["category"] == "scroll"]
    old_plan, new_plan = scroll_plans[0], scroll_plans[1]
    username, password = generate_vpn_credentials()
    customer_telegram_id = 5551234

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=customer_telegram_id, username=username, password=password,
            group_name=old_plan["group_name"], data_cap_mb=old_plan["data_cap_mb"], plan_id=old_plan["id"],
        )

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, username))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renew:plan:{new_plan['id']}"))

    async with async_session_maker() as session:
        refreshed = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))).scalar_one()
        plan = await get_plan(session, new_plan["id"])
    assert refreshed.plan_id == plan.id
    assert refreshed.ibsng_group == plan.group_name

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any(c[1]["chat_id"] == customer_telegram_id for c in sent)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "renewed" in edited[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_admin_renews_ibsng_only_username_not_tracked_locally(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.ibsng.client import IBSngClient

    scroll_plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll")

    async with IBSngClient() as client:
        await client.create_user(username="ibsng-only-admin-test", password="abc123", group_name="Trial-Iran", credit=512)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ibsng-only-admin-test"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renew:plan:{scroll_plan['id']}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "wasn't created through the bot" in edited[-1][1]["text"].lower()
