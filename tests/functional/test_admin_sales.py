"""Financial → Sales Status: full admins only, English only."""

from __future__ import annotations

from typing import Any

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


def _last_screen(fake_session: FakeBotSession) -> dict[str, Any]:
    screens = [c for c in fake_session.calls if c[0] in ("editMessageText", "sendMessage")]
    return screens[-1][1]


def _buttons(screen: dict[str, Any]) -> dict[str, str]:
    markup = screen.get("reply_markup") or {"inline_keyboard": []}
    return {b["text"]: b["callback_data"] for row in markup["inline_keyboard"] for b in row}


async def _enabled() -> bool:
    from app.services.sales_status import are_sales_enabled

    async with async_session_maker() as session:
        return await are_sales_enabled(session)


@pytest.mark.asyncio
async def test_financial_menu_shows_sales_status_to_a_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin"))
    assert _buttons(_last_screen(fake_session))["🛑 Sales Status"] == "adm:fin:sales"


@pytest.mark.asyncio
async def test_financial_menu_hides_sales_status_from_a_sales_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_admin(881, "sales")
    await dispatcher.feed_update(bot, make_callback_update(881, "adm:fin"))
    assert "🛑 Sales Status" not in _buttons(_last_screen(fake_session))


@pytest.mark.asyncio
async def test_a_sales_admin_cannot_switch_sales_off(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await _seed_admin(882, "sales")
    await dispatcher.feed_update(bot, make_callback_update(882, "adm:fin:sales:set:off"))
    assert await _enabled() is True
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_status_screen_defaults(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales"))
    screen = _last_screen(fake_session)
    assert "State: 🟢 Sales enabled" in screen["text"]
    assert screen["text"].count("(default)") == 2
    buttons = _buttons(screen)
    assert buttons["🔴 Disable Sales"] == "adm:fin:sales:set:off"
    assert buttons["✏️ Edit Message (FA)"] == "adm:fin:sales:msg:fa"
    assert buttons["✏️ Edit Message (EN)"] == "adm:fin:sales:msg:en"
    assert buttons["↩️ Reset Messages to Default"] == "adm:fin:sales:reset"
    assert buttons["⬅️ Back to Financial"] == "adm:fin"


@pytest.mark.asyncio
async def test_disabling_and_enabling_persist_and_rerender(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off"))
    assert await _enabled() is False
    screen = _last_screen(fake_session)
    assert "State: 🔴 Sales disabled" in screen["text"]
    assert _buttons(screen)["🟢 Enable Sales"] == "adm:fin:sales:set:on"

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:on"))
    assert await _enabled() is True


@pytest.mark.asyncio
async def test_the_change_is_logged_with_state_and_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off", username="boss"))

    topics = [c for c in fake_session.calls if c[0] == "createForumTopic"]
    assert topics and topics[-1][1]["name"] == "🛠 Admin Actions"
    logged = [c for c in fake_session.calls if c[0] == "sendMessage" and "SALES STATUS" in c[1]["text"]]
    assert len(logged) == 1
    text = logged[0][1]["text"]
    assert "🛑 <b>SALES STATUS</b>" in text
    assert "State: 🔴 DISABLED" in text
    assert f"Admin: @boss ({FAKE_ADMIN_ID})" in text
    assert "Time: " in text


@pytest.mark.asyncio
async def test_a_stale_button_that_changes_nothing_logs_nothing(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two admins, one old keyboard: a second 'Disable' must not flip
    sales back on, and must not post a second entry."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:set:off"))

    assert await _enabled() is False
    logged = [c for c in fake_session.calls if c[0] == "sendMessage" and "SALES STATUS" in c[1]["text"]]
    assert len(logged) == 1


@pytest.mark.asyncio
async def test_editing_the_persian_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:fa"))
    prompt = _last_screen(fake_session)
    assert "Persian" in prompt["text"]
    assert _buttons(prompt)["❌ Cancel"] == "adm:fin:sales"

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "  فروش تا فردا بسته است  "))

    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "fa") == "فروش تا فردا بسته است"
        assert await get_custom_paused_message(session, "en") is None
    screen = _last_screen(fake_session)
    assert "✅ Persian message saved." in screen["text"]
    assert "(custom)" in screen["text"] and "(default)" in screen["text"]


@pytest.mark.asyncio
async def test_an_oversized_message_is_refused_and_the_prompt_stays_open(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession
) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:en"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "x" * 3501))
    assert "3500" in _last_screen(fake_session)["text"]

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "Closed today"))
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "en") == "Closed today"


@pytest.mark.asyncio
async def test_an_empty_message_is_refused(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:en"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "   "))
    assert "non-empty" in _last_screen(fake_session)["text"]
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "en") is None


@pytest.mark.asyncio
async def test_cancel_leaves_the_edit(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:msg:en"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "should not be stored"))
    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "en") is None


@pytest.mark.asyncio
async def test_reset_restores_both_defaults(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.services.sales_status import get_custom_paused_message, set_custom_paused_message

    async with async_session_maker() as session:
        await set_custom_paused_message(session, "fa", "الف")
        await set_custom_paused_message(session, "en", "A")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:fin:sales:reset"))

    async with async_session_maker() as session:
        assert await get_custom_paused_message(session, "fa") is None
        assert await get_custom_paused_message(session, "en") is None
    assert _last_screen(fake_session)["text"].count("(default)") == 2
