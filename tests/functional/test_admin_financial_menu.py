"""The regrouped admin panel (epic part 1).

The load-bearing rule here is that no callback was renamed: a keyboard
already sitting in an admin's chat history is a live control surface, so
tapping last week's panel must still work.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


def _buttons(fake_session: FakeBotSession) -> dict[str, str]:
    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    markup = edited[-1][1].get("reply_markup") or {"inline_keyboard": []}
    return {b["text"]: b["callback_data"] for row in markup["inline_keyboard"] for b in row}


@pytest.mark.asyncio
async def test_root_menu_has_the_seven_agreed_entries(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:root"))

    buttons = _buttons(fake_session)
    assert buttons["👤 Users"] == "adm:users"
    assert buttons["💰 Financial"] == "adm:fin"
    assert buttons["📊 Reports"] == "adm:reports"
    assert buttons["📚 Tutorials & Profiles"] == "adm:tutorials"
    assert buttons["📢 Broadcast"] == "adm:broadcast"
    assert buttons["⚙️ System"] == "adm:settings"
    assert buttons["⬅️ Back to Menu"] == "menu:root"
    # Moved one level down, so no longer at the top.
    assert "🏷 Discount Codes" not in buttons
    assert "👥 Manage Admins" not in buttons


@pytest.mark.asyncio
async def test_financial_menu_lists_every_money_screen_for_a_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin"))

    buttons = _buttons(fake_session)
    assert buttons["🏷 Discount Codes"] == "adm:discounts"
    assert buttons["💰 Manage Plans"] == "adm:settings:plans"
    assert buttons["💳 Crypto Settlement Address"] == "adm:settings:crypto"
    assert buttons["💱 Crypto Coins"] == "adm:settings:coins"
    assert buttons["🔄 Recover Stuck Payments"] == "adm:settings:reconcile"
    assert any("back" in text.lower() for text in buttons)


@pytest.mark.asyncio
async def test_financial_menu_hides_full_only_screens_from_a_sales_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A visible button whose router filter rejects the tap gives zero
    feedback - the same reason Broadcast is hidden rather than gated."""
    await _seed_admin(880, "sales")

    await dispatcher.feed_update(bot, make_callback_update(880, "adm:fin"))

    buttons = _buttons(fake_session)
    assert "🏷 Discount Codes" in buttons and "💰 Manage Plans" in buttons
    for full_only in ("💳 Crypto Settlement Address", "💱 Crypto Coins", "🔄 Recover Stuck Payments"):
        assert full_only not in buttons


@pytest.mark.asyncio
async def test_system_menu_holds_plumbing_and_manage_admins(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings"))

    buttons = _buttons(fake_session)
    assert buttons["👥 Manage Admins"] == "adm:admins"
    assert "☎️ Support Contact" in buttons and "🎁 Trial Limit" in buttons
    # The money screens moved to Financial.
    for moved in ("💰 Manage Plans", "💱 Crypto Coins", "💳 Crypto Settlement Address"):
        assert moved not in buttons


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["adm:fin", "adm:reports", "adm:fin:revenue", "adm:fin:payments"])
async def test_support_admin_is_refused_the_money_screens(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    await _seed_admin(881, "support")

    await dispatcher.feed_update(bot, make_callback_update(881, data))

    assert not [c for c in fake_session.calls if c[0] == "editMessageText"]
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "heading"),
    [("adm:fin:revenue", "Revenue Overview"), ("adm:fin:payments", "Payments")],
)
async def test_financial_children_render_their_real_screens(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, data: str, heading: str
) -> None:
    """These were part 1 placeholders; part 2 replaced them with the real
    screens, and neither may fall through to a permission alert."""
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, data))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited and heading in edited[-1][1]["text"]
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("permission" in (c[1].get("text") or "").lower() for c in answered)



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    ["adm:discounts", "adm:settings:plans", "adm:settings:crypto", "adm:settings:coins", "adm:admins"],
)
async def test_moved_screens_are_still_reachable_by_their_original_callback(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, data))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert edited, f"{data} rendered nothing"
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("permission" in (c[1].get("text") or "").lower() for c in answered)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "parent"),
    [
        ("adm:discounts", "adm:fin"),
        ("adm:settings:plans", "adm:fin"),
        ("adm:settings:crypto", "adm:fin"),
        ("adm:settings:coins", "adm:fin"),
        ("adm:admins", "adm:settings"),
    ],
)
async def test_moved_screens_go_back_to_their_new_parent(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, data: str, parent: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, data))

    assert parent in set(_buttons(fake_session).values())


@pytest.mark.asyncio
async def test_recover_stuck_payments_returns_to_financial(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its own screen runs a live Plisio sweep, so the lookup is stubbed."""
    from app.bot.handlers import admin_settings

    async def _no_op(bot_: Any) -> dict[str, int]:
        return {"checked": 0, "activated": 0, "still_open": 0, "errors": 0}

    monkeypatch.setattr(admin_settings, "reconcile_pending_payments", _no_op)
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:settings:reconcile"))

    assert "adm:fin" in set(_buttons(fake_session).values())
