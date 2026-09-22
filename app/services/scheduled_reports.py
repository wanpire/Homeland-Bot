"""The scheduled half of the log group: hourly health, daily accounting.

Real-time categories (new user, purchase, renewal, trial) fire from their
own call sites; these are the ones that only make sense on a clock.

Every figure comes from the same query layer the in-panel Reports screen
reads, so the accounting summary an admin taps and the one posted at
08:00 UTC cannot disagree.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot

from app.db.session import async_session_maker
from app.services.adminlog import ACCOUNTING, SERVER_HEALTH, SERVER_HEALTH_ALERT, log_event
from app.services.health import run_health_check
from app.services.reporting import revenue_summary
from app.services.server_health import check_server_health

logger = logging.getLogger(__name__)

HEALTH_INTERVAL_SECONDS = 60 * 60
_ACCOUNTING_HOUR_UTC = 8


async def post_server_health(bot: Bot) -> None:
    health = check_server_health()
    await log_event(
        bot,
        SERVER_HEALTH if health.healthy else SERVER_HEALTH_ALERT,
        Disk=health.disk_text,
        Memory=health.memory_text,
        Load=health.load_text,
        Uptime=health.uptime_text,
        Detail=", ".join(health.problems) or None,
    )


async def post_accounting_summary(bot: Bot, *, period: str = "today") -> None:
    async with async_session_maker() as session:
        summary = await revenue_summary(session, period=period)

    providers = " · ".join(
        f"{name.title()} {totals.orders}/${totals.revenue}"
        for name, totals in summary.by_provider.items()
        if totals.orders
    )
    await log_event(
        bot,
        ACCOUNTING,
        Period=period,
        Revenue=f"${summary.revenue}",
        Orders=str(summary.paid_orders),
        Average=f"${summary.average_order}",
        Discounts=f"${summary.discounts_given}",
        Providers=providers or "none",
    )


async def run_hourly_health_loop(bot: Bot) -> None:
    """Both health categories, hourly.

    This replaces the previous state-change-only rule, which existed
    because a single shared group made "all ok" every fifteen minutes
    into noise. With a dedicated topic the reasoning inverts: an hourly
    heartbeat nobody has to read is reassurance, and its absence is
    itself a signal. run_health_check still posts immediately on a state
    change, so a failure does not wait up to an hour."""
    while True:
        try:
            await run_health_check(bot)
            await post_server_health(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Hourly health pass failed")
        await asyncio.sleep(HEALTH_INTERVAL_SECONDS)


def _seconds_until_hour(hour_utc: int) -> float:
    now = dt.datetime.now(dt.timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily_accounting_loop(bot: Bot) -> None:
    while True:
        await asyncio.sleep(_seconds_until_hour(_ACCOUNTING_HOUR_UTC))
        try:
            await post_accounting_summary(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily accounting pass failed")
