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


@pytest.mark.asyncio
async def test_renew_plan_shows_price_summary_with_no_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 820
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    text = edited[0][1]["text"]
    assert "1 Month" in text
    assert "$5.00" in text
    assert "Duration: 30 days" in text
    assert "Data: 10 GB" in text
    assert "<s>" not in text
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "✅ Renew" in buttons
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_plan_shows_auto_applied_public_discount(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from decimal import Decimal

    from app.services.discounts import create_discount_code

    telegram_id = 821
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        await create_discount_code(
            session, code="WELCOME10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True
        )

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    text = edited[0][1]["text"]
    assert "$5.00" in text
    assert "$4.50" in text
    assert "-10%" in text


@pytest.mark.asyncio
async def test_renew_plan_not_found_shows_gone_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 822
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_renew_plan_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 823
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 824
    intruder_id = 825
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:plan:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_plan_malformed_plan_id_degrades_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 826
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_shows_coming_soon_and_does_not_mutate_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, ibsng_server: FakeIBSngServer
) -> None:
    from app.services.ibsng.client import IBSngClient

    telegram_id = 827
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    original_group = service.ibsng_group
    original_plan_id = service.plan_id
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("back" in b.lower() for b in buttons)

    async with async_session_maker() as session:
        refreshed = await session.get(type(service), service.id)
    assert refreshed.ibsng_group == original_group
    assert refreshed.plan_id == original_plan_id

    async with IBSngClient() as client:
        live_group = await client.get_user_group(username=service.ibsng_username)
    assert live_group == original_group


@pytest.mark.asyncio
async def test_renew_confirm_not_found_shows_gone_message(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 828
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:999999"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_rejects_trial_plan_id(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    telegram_id = 829
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    trial_plan_id = _plan_id(seeded_catalog, category="trial", name="Trial")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{trial_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "no longer exists" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_rejects_another_users_service(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    owner_id = 830
    intruder_id = 831
    service = await _create_service(seeded_catalog, telegram_id=owner_id, category="stream", name="1 Month")
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(intruder_id, f"renew:confirm:{service.id}:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert "not found" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_confirm_malformed_ids_degrade_gracefully(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(832, "renew:confirm:not-a-number:also-not-a-number"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "not found" in edited[0][1]["text"].lower()
