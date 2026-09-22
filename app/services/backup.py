"""Nightly database backup, reported to the operational log group.

No backup existed before this: no script, no cron entry, no dumps on the
server. A status report about a backup that does not happen is worthless,
so the job that produces the status is here too.

The dump runs through the database container that already exists, using
the credentials already in its environment, so no new container and no
new secret is introduced.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot

from app.config import get_settings
from app.services.adminlog import BACKUP, log_event

logger = logging.getLogger(__name__)

BACKUP_DIR = Path("/backups")
RETENTION_DAYS = 14
_RUN_AT_HOUR_UTC = 3


@dataclass
class BackupResult:
    ok: bool
    path: Path | None = None
    size_bytes: int = 0
    kept: int = 0
    duration_seconds: float = 0.0
    error: str | None = None


def _human_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


async def run_backup_once() -> BackupResult:
    """Dump, compress, prune. Never raises: the caller reports the
    failure rather than letting the loop die on it."""
    settings = get_settings()
    started = time.monotonic()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    target = BACKUP_DIR / f"homeland-{stamp}.sql.gz"

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        command = (
            f"PGPASSWORD='{settings.postgres_password}' pg_dump "
            f"-h {settings.postgres_host} -p {settings.postgres_port} "
            f"-U {settings.postgres_user} {settings.postgres_db} | gzip -c"
        )
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            return BackupResult(
                ok=False,
                duration_seconds=time.monotonic() - started,
                error=(stderr or b"").decode("utf-8", "replace")[:200] or "pg_dump failed",
            )

        target.write_bytes(stdout)
        kept = _prune_old_backups()
        return BackupResult(
            ok=True,
            path=target,
            size_bytes=target.stat().st_size,
            kept=kept,
            duration_seconds=time.monotonic() - started,
        )
    except Exception as exc:
        logger.exception("Backup failed")
        return BackupResult(ok=False, duration_seconds=time.monotonic() - started, error=str(exc)[:200])


def _prune_old_backups() -> int:
    """Deletes dumps older than the retention window and returns how many
    remain, which is the number worth reporting: "kept 14" tells an admin
    the rotation is working."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETENTION_DAYS)
    remaining = 0
    for path in sorted(BACKUP_DIR.glob("homeland-*.sql.gz")):
        try:
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
        except OSError:
            continue
        if modified < cutoff:
            path.unlink(missing_ok=True)
        else:
            remaining += 1
    return remaining


async def run_backup_and_report(bot: Bot) -> BackupResult:
    result = await run_backup_once()
    if result.ok:
        await log_event(
            bot,
            BACKUP,
            Status="ok",
            File=result.path.name if result.path else None,
            Size=_human_size(result.size_bytes),
            Kept=f"{result.kept} file(s)",
            Duration=f"{result.duration_seconds:.1f}s",
        )
    else:
        # The failure is the case worth waking up for.
        await log_event(
            bot,
            BACKUP,
            Status="FAILED",
            Duration=f"{result.duration_seconds:.1f}s",
            Error=result.error,
        )
    return result


def _seconds_until_next_run() -> float:
    now = dt.datetime.now(dt.timezone.utc)
    target = now.replace(hour=_RUN_AT_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


async def run_backup_loop(bot: Bot) -> None:
    while True:
        await asyncio.sleep(_seconds_until_next_run())
        try:
            await run_backup_and_report(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Backup loop pass failed")


@dataclass
class BackupFile:
    name: str
    size_bytes: int
    age_seconds: float

    @property
    def size_text(self) -> str:
        return _human_size(self.size_bytes)

    @property
    def age_text(self) -> str:
        hours = self.age_seconds / 3600
        if hours < 1:
            return f"{int(self.age_seconds // 60)}m"
        if hours < 24:
            return f"{int(hours)}h"
        return f"{int(hours // 24)}d"


def backup_history(limit: int = 20) -> list[BackupFile]:
    """What is actually on disk, newest first. Read from the directory
    rather than a table: the files are the truth, and a row claiming a
    backup exists when the file is gone would be worse than no row."""
    try:
        paths = sorted(BACKUP_DIR.glob("homeland-*.sql.gz"), reverse=True)
    except OSError:
        return []

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    history: list[BackupFile] = []
    for path in paths[:limit]:
        try:
            stat = path.stat()
        except OSError:
            continue
        history.append(
            BackupFile(name=path.name, size_bytes=stat.st_size, age_seconds=max(0.0, now - stat.st_mtime))
        )
    return history
