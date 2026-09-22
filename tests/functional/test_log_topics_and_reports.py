"""Forum-topic routing for the log group, the scheduled posts, and the
expanded Reports screens."""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update
from tests.fakes.fake_bot_session import FakeBotSession
from tests.fakes.fake_ibsng_server import FakeIBSngServer

_CHAT_ID = -1004466777356


@pytest.fixture(autouse=True)
def _enable_log_group(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", str(_CHAT_ID))


def _created_topics(fake_session: FakeBotSession) -> list[str]:
    return [c[1]["name"] for c in fake_session.calls if c[0] == "createForumTopic"]


def _sent(fake_session: FakeBotSession) -> list[dict[str, Any]]:
    return [c[1] for c in fake_session.calls if c[0] == "sendMessage"]


def _screen(fake_session: FakeBotSession) -> str:
    return [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]["text"]


async def _seed_admin(telegram_id: int, level: str) -> None:
    from app.db.models.admin_user import AdminUser

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=telegram_id, level=level))
        await session.commit()


# --- topic routing ---


@pytest.mark.asyncio
async def test_a_topic_is_created_once_and_then_reused(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.adminlog import NEW_USER, log_event

    await log_event(bot, NEW_USER, User="@a", Language="fa")
    await log_event(bot, NEW_USER, User="@b", Language="en")

    assert _created_topics(fake_session) == ["🆕 New Users"]
    threads = {m["message_thread_id"] for m in _sent(fake_session)}
    assert len(threads) == 1 and None not in threads


@pytest.mark.asyncio
async def test_the_thread_id_is_stored_in_app_config(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    """Not hardcoded and not only in memory: a restart must reuse it."""
    from app.services.adminlog import PURCHASE, log_event
    from app.services.app_config import get_config

    await log_event(bot, PURCHASE, User="@a", Plan="1 Month", Amount="$5.00")

    async with async_session_maker() as session:
        stored = await get_config(session, "log_topic:purchase")
    assert stored is not None
    assert int(stored) == _sent(fake_session)[-1]["message_thread_id"]


@pytest.mark.asyncio
async def test_each_category_lands_in_its_own_thread(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.adminlog import NEW_USER, PURCHASE, RENEWAL, TRIAL, log_event

    for key in (NEW_USER, PURCHASE, RENEWAL, TRIAL):
        await log_event(bot, key, User="@a")

    threads = [m["message_thread_id"] for m in _sent(fake_session)]
    assert len(set(threads)) == 4


@pytest.mark.asyncio
async def test_ok_and_alert_of_one_kind_share_a_thread(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.adminlog import HEALTH_ALERT, HEALTH_OK, log_event

    await log_event(bot, HEALTH_ALERT, Component="IBSng", Detail="timed out")
    await log_event(bot, HEALTH_OK, Component="IBSng", Detail="12 group(s)")

    assert _created_topics(fake_session) == ["🩺 Service Health"]
    assert len({m["message_thread_id"] for m in _sent(fake_session)}) == 1


@pytest.mark.asyncio
async def test_a_failed_topic_creation_falls_back_to_the_general_thread(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing filing cabinet must never lose the entry."""
    from app.services.adminlog import TRIAL, log_event

    async def _refuse(*args: Any, **kwargs: Any) -> Any:
        raise TelegramBadRequest(method=None, message="Bad Request: the chat is not a forum")  # type: ignore[arg-type]

    monkeypatch.setattr(bot, "create_forum_topic", _refuse)

    await log_event(bot, TRIAL, User="@a", Plan="Trial", Account="ir.x")

    sent = _sent(fake_session)
    assert len(sent) == 1
    assert sent[0].get("message_thread_id") is None


@pytest.mark.asyncio
async def test_ensure_all_topics_creates_eight_and_is_idempotent(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.logtopics import ensure_all_topics

    first = await ensure_all_topics(bot, _CHAT_ID)
    assert len(first) == 8
    assert all(outcome.startswith("created") for outcome in first.values())
    assert len(_created_topics(fake_session)) == 8

    fake_session.reset()
    second = await ensure_all_topics(bot, _CHAT_ID)
    assert set(second.values()) == {"already set up"}
    assert not _created_topics(fake_session)


@pytest.mark.asyncio
async def test_logtopics_command_reports_each_topic(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/logtopics"))

    reply = [m for m in _sent(fake_session) if m["chat_id"] == FAKE_ADMIN_ID][-1]["text"]
    for name in ("🆕 New Users", "💰 Purchases", "♻️ Renewals", "🎁 Trials",
                 "💾 Backups", "🖥 Server Health", "🩺 Service Health", "📊 Accounting"):
        assert name in reply


@pytest.mark.asyncio
async def test_logtopics_is_ignored_for_a_non_full_admin(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await _seed_admin(7100, "sales")

    await dispatcher.feed_update(bot, make_message_update(7100, "/logtopics"))

    # The middleware registering this admin as a user may file a New User
    # entry; what must not happen is the full setup run.
    assert "💾 Backups" not in _created_topics(fake_session)
    assert not [m for m in _sent(fake_session) if "Log group topics" in m["text"]]


# --- server health ---


def test_server_health_flags_a_full_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import server_health

    class _Usage:
        total, used, free = 100 * 1024**3, 90 * 1024**3, 10 * 1024**3

    monkeypatch.setattr(server_health.shutil, "disk_usage", lambda path: _Usage())
    monkeypatch.setattr(server_health, "_memory_used_percent", lambda: 40.0)

    health = server_health.check_server_health()

    assert not health.healthy
    assert health.problems == ["disk 90% full"]


def test_server_health_flags_memory_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import server_health

    class _Usage:
        total, used, free = 100 * 1024**3, 10 * 1024**3, 90 * 1024**3

    monkeypatch.setattr(server_health.shutil, "disk_usage", lambda path: _Usage())
    monkeypatch.setattr(server_health, "_memory_used_percent", lambda: 95.0)

    assert server_health.check_server_health().problems == ["memory 95% used"]


def test_server_health_below_thresholds_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import server_health

    class _Usage:
        total, used, free = 100 * 1024**3, 30 * 1024**3, 70 * 1024**3

    monkeypatch.setattr(server_health.shutil, "disk_usage", lambda path: _Usage())
    monkeypatch.setattr(server_health, "_memory_used_percent", lambda: None)

    health = server_health.check_server_health()
    assert health.healthy
    assert health.memory_text == "unknown"
    assert health.disk_text == "30% used · 70.0 GB free"


# --- scheduled posts ---


@pytest.mark.asyncio
async def test_server_health_post_goes_to_the_server_topic(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.services.scheduled_reports import post_server_health

    await post_server_health(bot)

    assert _created_topics(fake_session) == ["🖥 Server Health"]
    assert "SERVER" in _sent(fake_session)[-1]["text"]
    assert "Disk:" in _sent(fake_session)[-1]["text"]


@pytest.mark.asyncio
async def test_accounting_post_uses_the_revenue_definition(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.payment import Payment
    from app.services.scheduled_reports import post_accounting_summary

    plan_id = next(p["id"] for p in seeded_catalog["plans"] if p["category"] == "scroll")
    now = dt.datetime.now(dt.timezone.utc)
    async with async_session_maker() as session:
        for status, amount in (("paid", "7.00"), ("pending", "99.00")):
            session.add(Payment(
                telegram_id=7200, purpose="purchase", plan_id=plan_id, group_name="2W-1U-Iran-5G",
                data_cap_mb=5120, amount_usd=Decimal(amount), provider="plisio", status=status,
                created_at=now, resolved_at=now if status == "paid" else None,
            ))
        await session.commit()

    await post_accounting_summary(bot)

    assert _created_topics(fake_session) == ["📊 Accounting"]
    text = _sent(fake_session)[-1]["text"]
    assert "Revenue: $7.00" in text
    assert "Orders: 1" in text
    assert "99" not in text


@pytest.mark.asyncio
async def test_hourly_loop_posts_both_health_kinds(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from app.services import health, scheduled_reports

    async def _all_fine() -> dict[str, tuple[bool, str]]:
        return {"Database": (True, "ok")}

    async def _true() -> bool:
        return True

    async def _stop(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(health, "check_all", _all_fine)
    monkeypatch.setattr(health, "_heartbeat_due", lambda: _true())
    monkeypatch.setattr(scheduled_reports.asyncio, "sleep", _stop)

    with pytest.raises(asyncio.CancelledError):
        await scheduled_reports.run_hourly_health_loop(bot)

    assert set(_created_topics(fake_session)) == {"🩺 Service Health", "🖥 Server Health"}


# --- report screens ---


@pytest.mark.asyncio
async def test_reports_menu_lists_every_report(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports"))

    edit = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]
    callbacks = {b["callback_data"] for row in edit["reply_markup"]["inline_keyboard"] for b in row}
    for suffix in ("overview", "signups", "sales", "accounting", "service", "server", "backups"):
        assert f"adm:reports:{suffix}" in callbacks


@pytest.mark.asyncio
@pytest.mark.parametrize("report", ["signups", "sales", "accounting"])
@pytest.mark.parametrize("period", ["today", "7d", "30d", "all"])
async def test_period_reports_render_every_period(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, report: str, period: str
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"adm:reports:{report}:{period}"))

    edit = [c for c in fake_session.calls if c[0] == "editMessageText"][-1][1]
    callbacks = {b["callback_data"] for row in edit["reply_markup"]["inline_keyboard"] for b in row}
    # The period selector stays on the report it belongs to.
    assert f"adm:reports:{report}:7d" in callbacks


@pytest.mark.asyncio
async def test_signups_report_counts_new_users(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    from app.db.models.bot_user import BotUser

    now = dt.datetime.now(dt.timezone.utc)
    async with async_session_maker() as session:
        session.add(BotUser(telegram_id=7300, username=None, first_seen_at=now))
        session.add(BotUser(telegram_id=7301, username=None, first_seen_at=now - dt.timedelta(days=20)))
        await session.commit()

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports:signups:7d"))

    # The tapping admin is registered by the user middleware too, so the
    # week holds 7300 plus the admin; 7301 is outside it.
    text = _screen(fake_session)
    assert "New users: <b>2</b>" in text
    assert "All-time users: 3" in text


@pytest.mark.asyncio
async def test_service_health_screen_lists_components(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    ibsng_server: FakeIBSngServer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bot.handlers import reports

    async def _mixed() -> dict[str, tuple[bool, str]]:
        return {"Database": (True, "ok"), "IBSng": (False, "timed out")}

    monkeypatch.setattr(reports, "check_all", _mixed)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports:service"))

    text = _screen(fake_session)
    assert "💚 Database: ok" in text
    assert "🔴 IBSng: timed out" in text


@pytest.mark.asyncio
async def test_server_health_screen_renders(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict
) -> None:
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports:server"))

    text = _screen(fake_session)
    assert "Server Health" in text
    assert "Disk:" in text


@pytest.mark.asyncio
async def test_backups_screen_lists_files_newest_first(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import backup

    for name, age in (("homeland-20260920-030000.sql.gz", 3), ("homeland-20260922-030000.sql.gz", 1)):
        path = tmp_path / name
        path.write_bytes(b"x" * 2048)
        stamp = (dt.datetime.now() - dt.timedelta(days=age)).timestamp()
        os.utime(path, (stamp, stamp))
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports:backups"))

    text = _screen(fake_session)
    assert "2 kept" in text
    assert text.index("20260922") < text.index("20260920")


@pytest.mark.asyncio
async def test_backups_screen_with_no_backups_says_so(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import backup

    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "missing")

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "adm:reports:backups"))

    assert "No backups found yet" in _screen(fake_session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data", ["adm:reports", "adm:reports:signups", "adm:reports:sales", "adm:reports:accounting",
             "adm:reports:service", "adm:reports:server", "adm:reports:backups"],
)
async def test_support_admin_is_refused_every_report(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, data: str
) -> None:
    await _seed_admin(7400, "support")

    await dispatcher.feed_update(bot, make_callback_update(7400, data))

    assert not [c for c in fake_session.calls if c[0] == "editMessageText"]
    answered = [c for c in fake_session.calls if c[0] == "answerCallbackQuery"]
    assert answered and answered[-1][1].get("show_alert") is True
