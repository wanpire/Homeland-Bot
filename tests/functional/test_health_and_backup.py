"""Health checks and the nightly backup (epic part 5).

The health design is about silence: a check that announces "all ok"
every fifteen minutes is how a log group becomes unreadable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.fakes.fake_bot_session import FakeBotSession


def _entries(fake_session: FakeBotSession) -> list[str]:
    return [c[1]["text"] for c in fake_session.calls if c[0] == "sendMessage"]


@pytest.fixture(autouse=True)
def _enable_log_group(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_log_chat_id", "-1004466777356")


@pytest.mark.asyncio
async def test_a_healthy_component_is_not_announced_on_first_sight(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence is the normal state; only news is posted."""
    from app.services import health

    async def _all_fine() -> dict[str, tuple[bool, str]]:
        return {"Database": (True, "ok")}

    monkeypatch.setattr(health, "check_all", _all_fine)
    monkeypatch.setattr(health, "_heartbeat_due", lambda: _false())

    await health.run_health_check(bot)

    assert not [text for text in _entries(fake_session) if "HEALTH" in text]


async def _false() -> bool:
    return False


@pytest.mark.asyncio
async def test_a_failure_then_a_recovery_are_each_announced_once(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import health

    state = {"healthy": False}

    async def _check() -> dict[str, tuple[bool, str]]:
        return {"IBSng": (state["healthy"], "timed out" if not state["healthy"] else "12 group(s)")}

    monkeypatch.setattr(health, "check_all", _check)
    monkeypatch.setattr(health, "_heartbeat_due", lambda: _false())

    await health.run_health_check(bot)
    alerts = [text for text in _entries(fake_session) if "HEALTH ALERT" in text]
    assert len(alerts) == 1 and "IBSng" in alerts[0]

    # Unchanged: nothing new to say.
    fake_session.reset()
    await health.run_health_check(bot)
    assert not [text for text in _entries(fake_session) if "HEALTH" in text]

    fake_session.reset()
    state["healthy"] = True
    await health.run_health_check(bot)
    assert [text for text in _entries(fake_session) if "HEALTH OK" in text]


@pytest.mark.asyncio
async def test_a_raising_check_does_not_take_down_the_pass(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import health

    async def _boom() -> tuple[bool, str]:
        raise RuntimeError("exploded")

    monkeypatch.setattr(health, "CHECKS", {"Boom": _boom})

    results = await health.check_all()

    assert results["Boom"][0] is False


@pytest.mark.asyncio
async def test_backup_reports_success_with_size_and_retention(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.services import backup

    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)

    class _Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"-- dump contents" * 100, b""

    async def _fake_shell(command: str, **kwargs: Any) -> _Process:
        assert "pg_dump" in command and "gzip" in command
        return _Process()

    monkeypatch.setattr(backup.asyncio, "create_subprocess_shell", _fake_shell)

    result = await backup.run_backup_and_report(bot)

    assert result.ok and result.path is not None and result.path.exists()
    entry = [text for text in _entries(fake_session) if "BACKUP" in text][-1]
    assert "Status: ok" in entry
    assert "homeland-" in entry
    assert "Kept: 1 file(s)" in entry


@pytest.mark.asyncio
async def test_backup_reports_a_failure_rather_than_raising(
    bot: Any, fake_session: FakeBotSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The failure is the case worth waking up for, so it must reach the
    group rather than crash the loop."""
    from app.services import backup

    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)

    class _Process:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"could not connect to server"

    async def _fake_shell(command: str, **kwargs: Any) -> _Process:
        return _Process()

    monkeypatch.setattr(backup.asyncio, "create_subprocess_shell", _fake_shell)

    result = await backup.run_backup_and_report(bot)

    assert result.ok is False
    entry = [text for text in _entries(fake_session) if "BACKUP" in text][-1]
    assert "Status: FAILED" in entry
    assert "could not connect" in entry


def test_retention_deletes_only_old_dumps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import datetime as dt
    import os

    from app.services import backup

    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)

    fresh = tmp_path / "homeland-20260923-0300.sql.gz"
    stale = tmp_path / "homeland-20260101-0300.sql.gz"
    for path in (fresh, stale):
        path.write_bytes(b"x")
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=backup.RETENTION_DAYS + 1)).timestamp()
    os.utime(stale, (old, old))

    kept = backup._prune_old_backups()

    assert kept == 1
    assert fresh.exists() and not stale.exists()
