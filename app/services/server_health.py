"""Host-level health: disk, memory, load, uptime.

Distinct from service health, which asks whether the moving parts answer.
This asks whether the machine they run on is in trouble - the two fail
for different reasons and get fixed by different people.

Standard library only: no new dependency for four numbers.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: The filesystem holding the database and the backups. Inside the
#: container both live under /, which is the host's disk through the
#: volume mounts.
WATCHED_PATH = Path("/")

#: The two that actually page someone. A disk that fills stops Postgres
#: writing; memory exhaustion gets the process killed.
DISK_ALERT_PERCENT = 85.0
MEMORY_ALERT_PERCENT = 90.0

_STARTED_AT = time.monotonic()


@dataclass
class ServerHealth:
    disk_used_percent: float
    disk_free_gb: float
    memory_used_percent: float | None
    load_1m: float | None
    uptime_seconds: float
    problems: list[str]

    @property
    def healthy(self) -> bool:
        return not self.problems

    @property
    def disk_text(self) -> str:
        return f"{self.disk_used_percent:.0f}% used · {self.disk_free_gb:.1f} GB free"

    @property
    def memory_text(self) -> str:
        return "unknown" if self.memory_used_percent is None else f"{self.memory_used_percent:.0f}% used"

    @property
    def load_text(self) -> str:
        return "unknown" if self.load_1m is None else f"{self.load_1m:.2f}"

    @property
    def uptime_text(self) -> str:
        hours, remainder = divmod(int(self.uptime_seconds), 3600)
        if hours >= 24:
            return f"{hours // 24}d {hours % 24}h"
        return f"{hours}h {remainder // 60}m"


def _memory_used_percent() -> float | None:
    """Read from /proc/meminfo rather than pulling in psutil. Returns
    None off Linux or if the format is not what we expect, which reads
    as "unknown" rather than a fabricated number."""
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                values[key] = int(parts[0])
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if not total or available is None:
            return None
        return (total - available) * 100 / total
    except (OSError, ValueError):
        return None


def check_server_health() -> ServerHealth:
    """Never raises: a health check that crashes tells you nothing."""
    problems: list[str] = []

    try:
        usage = shutil.disk_usage(WATCHED_PATH)
        disk_used_percent = usage.used * 100 / usage.total if usage.total else 0.0
        disk_free_gb = usage.free / (1024**3)
    except OSError as exc:
        logger.warning("Could not read disk usage: %s", exc)
        disk_used_percent, disk_free_gb = 0.0, 0.0
        problems.append("disk usage unreadable")

    if disk_used_percent >= DISK_ALERT_PERCENT:
        problems.append(f"disk {disk_used_percent:.0f}% full")

    memory_used_percent = _memory_used_percent()
    if memory_used_percent is not None and memory_used_percent >= MEMORY_ALERT_PERCENT:
        problems.append(f"memory {memory_used_percent:.0f}% used")

    try:
        load_1m = os.getloadavg()[0]
    except (OSError, AttributeError):
        load_1m = None

    return ServerHealth(
        disk_used_percent=disk_used_percent,
        disk_free_gb=disk_free_gb,
        memory_used_percent=memory_used_percent,
        load_1m=load_1m,
        uptime_seconds=time.monotonic() - _STARTED_AT,
        problems=problems,
    )
