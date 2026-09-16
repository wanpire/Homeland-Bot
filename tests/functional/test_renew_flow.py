from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer


async def _create_service(seeded_catalog: dict, *, telegram_id: int, category: str, name: str, is_trial: bool = False):
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    plan = next(p for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client, telegram_id=telegram_id, username=username, password=password,
            group_name=plan["group_name"], data_cap_mb=plan["data_cap_mb"], plan_id=plan["id"], is_trial=is_trial,
        )
    return vpn_user


@pytest.mark.asyncio
async def test_list_renewable_services_excludes_trial(seeded_catalog: dict) -> None:
    from app.services.vpn_users import list_renewable_services

    telegram_id = 801
    paid = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)

    async with async_session_maker() as session:
        rows = await list_renewable_services(session, telegram_id)

    assert [vpn_user.id for vpn_user, _plan in rows] == [paid.id]


@pytest.mark.asyncio
async def test_menu_renew_shows_empty_state_when_no_services(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(802, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "don't have any services" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "🔑 Buy Subscription" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_menu_renew_lists_non_trial_services_only(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 803
    paid = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")
    await _create_service(seeded_catalog, telegram_id=telegram_id, category="trial", name="Trial", is_trial=True)

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, "menu:renew"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    texts = [b["text"] for b in buttons]
    assert "1 Month" in texts
    assert not any("trial" in t.lower() for t in texts)
    callback_by_text = {b["text"]: b["callback_data"] for b in buttons}
    assert callback_by_text["1 Month"] == f"renew:service:{paid.id}"


@pytest.mark.asyncio
async def test_menu_renew_is_no_longer_a_placeholder(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(804, "menu:renew"))

    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert not any("coming soon" in c[1].get("text", "").lower() for c in answered)


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_renew_service_shows_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 805
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Renew 1 Month" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🌊 Stream" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_service_unknown_id_shows_not_found(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(806, "renew:service:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_service_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 807
    intruder_id = 808
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:service:{service.id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_service_malformed_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(809, "renew:service:not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_category_shows_scroll_tiers_with_prices(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 810
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:category:{service.id}:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    buttons = [b["text"] for b in all_buttons]
    assert "2 Weeks — $3.00 (5 GB)" in buttons
    assert "1 Month — $5.00 (10 GB)" in buttons
    assert "2 Months — $9.00 (20 GB)" in buttons

    callback_data_by_text = {b["text"]: b["callback_data"] for b in all_buttons}
    for name in ("2 Weeks", "1 Month", "2 Months"):
        plan_id = _plan_id(seeded_catalog, category="scroll", name=name)
        matching = next(cb for text, cb in callback_data_by_text.items() if text.startswith(f"{name} — "))
        assert matching == f"renew:plan:{service.id}:{plan_id}"


@pytest.mark.asyncio
async def test_renew_category_invalid_category_redirects_to_category_picker(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 811
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:category:{service.id}:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Pick a category" in edited[0][1]["text"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "📜 Scroll" in buttons
    assert "🌊 Stream" in buttons


@pytest.mark.asyncio
async def test_renew_category_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 812
    intruder_id = 813
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:category:{service.id}:scroll"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()
