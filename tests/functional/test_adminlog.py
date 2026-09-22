"""The operational log group's format and safety (epic part 5)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.services.adminlog import EVENTS, render_event

_WHEN = dt.datetime(2026, 9, 23, 14, 2, tzinfo=dt.timezone.utc)


def test_every_category_has_a_distinct_emoji_and_title() -> None:
    """The first line is what an admin sorts by when scrolling, so no two
    categories may share it."""
    emojis = [event.emoji for event in EVENTS.values()]
    titles = [event.title for event in EVENTS.values()]
    assert len(set(emojis)) == len(emojis)
    assert len(set(titles)) == len(titles)


def test_purchase_renders_its_fields_in_order() -> None:
    text = render_event(
        "purchase",
        {
            "User": "@someone (179494847)", "Plan": "1 Month (Scroll)", "Amount": "$5.00",
            "Provider": "plisio", "Account": "ir.abc123",
        },
        now=_WHEN,
    )

    lines = text.split("\n")
    assert lines[0] == "💰 <b>PURCHASE</b>"
    assert [line.split(":")[0] for line in lines[1:-1]] == ["User", "Plan", "Amount", "Provider", "Account"]
    assert lines[-1] == "Time: 2026-09-23 14:02 UTC"


def test_absent_fields_are_omitted_not_printed_blank() -> None:
    """A column of empty "Detail:" lines is exactly the noise this format
    exists to avoid."""
    text = render_event("health_alert", {"Component": "IBSng"}, now=_WHEN)

    assert "Component: IBSng" in text
    assert "Detail" not in text
    assert "Checks" not in text


def test_values_are_escaped() -> None:
    text = render_event("new_user", {"User": "@a<b>&c"}, now=_WHEN)

    assert "<b>&amp;c" not in text.split("\n")[0]
    assert "&lt;b&gt;" in text


def test_unlisted_values_are_never_printed() -> None:
    """A typo at a call site must not silently reshape an entry."""
    text = render_event("new_user", {"User": "@someone", "Langauge": "fa"}, now=_WHEN)

    assert "Langauge" not in text
    assert "fa" not in text


@pytest.mark.asyncio
async def test_disabled_when_the_chat_id_is_unset(bot: Any, fake_session: Any) -> None:
    from app.config import get_settings
    from app.services.adminlog import log_event

    assert get_settings().admin_log_chat_id == ""
    await log_event(bot, "new_user", User="@someone")

    assert not [c for c in fake_session.calls if c[0] == "sendMessage"]


@pytest.mark.asyncio
async def test_a_telegram_failure_is_swallowed(bot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Logging is observation, not a step in any transaction: a removed
    bot must never fail the purchase that triggered the entry."""
    from aiogram.exceptions import TelegramAPIError

    from app.config import get_settings
    from app.services.adminlog import log_event

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise TelegramAPIError(method=None, message="bot is not a member of the group")

    monkeypatch.setattr(bot, "send_message", _boom)

    await log_event(bot, "purchase", User="@someone", Amount="$5.00")


@pytest.mark.asyncio
async def test_a_malformed_chat_id_is_reported_not_raised(bot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.adminlog import log_event

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "not-a-number")

    await log_event(bot, "purchase", User="@someone")


@pytest.mark.asyncio
async def test_an_unknown_category_is_refused_quietly(bot: Any, fake_session: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.adminlog import log_event

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")

    await log_event(bot, "no_such_category", User="@someone")

    assert not [c for c in fake_session.calls if c[0] == "sendMessage"]


@pytest.mark.asyncio
async def test_a_configured_group_receives_the_entry(bot: Any, fake_session: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.adminlog import log_event

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")

    await log_event(bot, "trial", User="@someone", Plan="Trial", Account="ir.t00001")

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == -1004466777356
    assert "🎁 <b>TRIAL</b>" in sent[0][1]["text"]
