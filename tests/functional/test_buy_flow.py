from __future__ import annotations

from typing import Any

import pytest

from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


@pytest.mark.asyncio
async def test_buy_shows_category_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🌊 Stream" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_category_shows_scroll_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    buttons = [b["text"] for b in all_buttons]
    assert "2 Weeks — $3.00" in buttons
    assert "1 Month — $5.00" in buttons
    assert "2 Months — $9.00" in buttons
    assert any("back" in b.lower() for b in buttons)

    callback_data_by_text = {b["text"]: b["callback_data"] for b in all_buttons}
    for name in ("2 Weeks", "1 Month", "2 Months"):
        plan_id = _plan_id(seeded_catalog, category="scroll", name=name)
        matching = next(cb for text, cb in callback_data_by_text.items() if text.startswith(f"{name} — "))
        assert matching == f"buy:plan:{plan_id}"


@pytest.mark.asyncio
async def test_buy_category_shows_stream_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:stream"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    buttons = [b["text"] for b in all_buttons]
    assert "1 Month — $12.00" in buttons
    assert "2 Months — $20.00" in buttons
    assert "3 Months — $29.00" in buttons

    callback_data_by_text = {b["text"]: b["callback_data"] for b in all_buttons}
    for name in ("1 Month", "2 Months", "3 Months"):
        plan_id = _plan_id(seeded_catalog, category="stream", name=name)
        matching = next(cb for text, cb in callback_data_by_text.items() if text.startswith(f"{name} — "))
        assert matching == f"buy:plan:{plan_id}"


@pytest.mark.asyncio
async def test_buy_category_invalid_category_redirects_to_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    """A malformed/spoofed `buy:category:xyz` (and, more to the point,
    `buy:category:trial` — Trial has its own dedicated flow) must not
    silently render an empty tier list; it should bounce back to the
    category picker."""
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "Pick a category" in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🌊 Stream" in buttons


@pytest.mark.asyncio
async def test_buy_category_nonsense_category_redirects_to_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:category:xyz"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Pick a category" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_menu_buy_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "menu:buy"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_buy_plan_shows_price_summary_with_no_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "1 Month" in text
    assert "$5.00" in text
    assert "Duration: 30 days" in text
    assert "Data: 10 GB" in text
    assert "<s>" not in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "✅ Buy" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_plan_shows_auto_applied_public_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.db.session import async_session_maker
    from app.services.discounts import create_discount_code

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="WELCOME10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True
        )

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$4.50" in text
    assert "-10%" in text


@pytest.mark.asyncio
async def test_buy_plan_ignores_private_discount_codes(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.db.session import async_session_maker
    from app.services.discounts import create_discount_code

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="PRIVATE50", percent=Decimal("50"), usage_limit=None, plan_ids=[plan_id], is_public=False
        )

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$2.50" not in text


@pytest.mark.asyncio
async def test_buy_plan_not_found_shows_gone_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:plan:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_confirm_shows_coming_soon_and_creates_no_account(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from sqlalchemy import select

    from app.db.models.vpn_user import VPNUser
    from app.db.session import async_session_maker

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)

    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser))).scalars().all()
    assert list(rows) == []
    assert ibsng_server.user_count() == 0


@pytest.mark.asyncio
async def test_buy_confirm_not_found_shows_gone_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(999, "buy:confirm:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_buy_plan_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """A crafted `buy:plan:<trial-plan-id>` must not render a normal-looking
    $0.00 purchase screen — Trial is real (category="trial", $0.00) but
    Buy must never expose it; that's menu:trial's job."""
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_buy_confirm_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
