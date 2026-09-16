from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from app.services.ibsng.exceptions import IBSngError
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_admin_cannot_start_renew_flow(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "adm:users:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited == []


@pytest.mark.asyncio
async def test_admin_renews_unknown_ibsng_username_shows_not_found(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """The namespace guard looks the account up at the username step, so
    "not found" now lands before a plan is ever offered - there is no
    plan-pick step left to reach."""
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "ghost-user"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert "not found" in sent[-1][1]["text"].lower()
    assert "pick the plan" not in sent[-1][1]["text"].lower()


@pytest.mark.asyncio
async def test_admin_renew_refuses_a_non_homeland_ibsng_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """Homeland shares its IBSng instance with AloBot (CLAUDE.md,
    app/services/groups.py). A typed/pasted AloBot username must be
    refused outright - never renewed, never moved into a Homeland pricing
    group."""
    from app.services.ibsng.client import IBSngClient

    alobot_username = "alobot-customer"
    alobot_group = "1M-1U-Prime"  # a seeded non-Homeland group on the fake shared instance

    async with IBSngClient() as client:
        await client.create_user(
            username=alobot_username, password="abc123", group_name=alobot_group, credit=1024
        )

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, alobot_username))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    refusal = sent[-1][1]
    assert "isn't a homeland account" in refusal["text"].lower()
    assert alobot_group in refusal["text"]

    # (b) no plan picker was offered - not in the text, and not as buttons.
    assert "pick the plan" not in refusal["text"].lower()
    plan_buttons = [
        b
        for c in fake_session.calls
        if c[0] in ("sendMessage", "editMessageText")
        for row in (c[1].get("reply_markup") or {}).get("inline_keyboard", [])
        for b in row
        if b.get("callback_data", "").startswith("adm:users:renew:plan:")
    ]
    assert plan_buttons == []

    # (c) renew_and_change_group never ran - the account is untouched.
    async with IBSngClient() as client:
        assert await client.get_user_group(username=alobot_username) == alobot_group


@pytest.mark.asyncio
async def test_renew_username_with_html_chars_is_escaped_in_not_found_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """The bot's default parse mode is HTML - an admin-typed username
    containing a raw &, <, or > must be escaped before it's interpolated
    into the namespace guard's "not found" message."""
    unsafe_username = "ghost<b>&user"

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, unsafe_username))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    text = sent[-1][1]["text"]
    assert "not found" in text.lower()
    assert "ghost&lt;b&gt;&amp;user" in text
    assert "ghost<b>&user" not in text


@pytest.mark.asyncio
async def test_renew_ibsng_error_message_is_escaped_in_result(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An IBSngError's message originates from the IBSng server itself -
    a remote system shared with a sibling bot project, and the one
    genuinely untrusted external text source in this handler - so it
    must be escaped before landing in an HTML-parse-mode message."""
    import app.bot.handlers.admin_renew as admin_renew_handler
    from app.services.ibsng.client import IBSngClient

    scroll_plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll")
    homeland_username = "homeland-renew-error-test"

    async with IBSngClient() as client:
        await client.create_user(username=homeland_username, password="abc123", group_name="Trial-Iran", credit=512)

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise IBSngError("upstream said <b>bad & broken</b>")

    monkeypatch.setattr(admin_renew_handler, "renew_and_change_group", _boom)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:users:renew"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, homeland_username))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:users:renew:plan:{scroll_plan['id']}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[-1][1]["text"]
    assert "upstream said &lt;b&gt;bad &amp; broken&lt;/b&gt;" in text
    assert "<b>bad & broken</b>" not in text


@pytest.mark.asyncio
async def test_admin_renews_bot_created_account_updates_row_and_notifies_user(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.vpn_user import VPNUser
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

    # Compared against the seeded_catalog row directly, NOT against a
    # re-fetch of whatever row `new_plan["id"]` happens to resolve to -
    # the re-fetch version passed even while the fixture's cached ids had
    # drifted off the real rows, because it compared a value to itself.
    async with async_session_maker() as session:
        refreshed = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))).scalar_one()
    assert refreshed.plan_id == new_plan["id"]
    assert refreshed.ibsng_group == new_plan["group_name"]

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
