"""Periodic health checks for the operational log group.

Noise control is the design, not an afterthought. A check that announces
"all ok" every fifteen minutes is how a log group becomes unreadable, so
an entry is posted only when a component's state CHANGES, plus one
heartbeat a day so silence stays distinguishable from a dead bot.

Previous state lives in Redis, so a restart does not re-announce every
component that was already fine.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from redis.exceptions import RedisError
from sqlalchemy import text

from app.db.session import async_session_maker
from app.redis import get_redis
from app.services.adminlog import HEALTH_ALERT, HEALTH_OK, log_event

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 15 * 60
HEARTBEAT_INTERVAL_SECONDS = 24 * 60 * 60

_STATE_KEY = "homeland:health:{component}"
_HEARTBEAT_KEY = "homeland:health:heartbeat"

OK = "ok"


async def _check_database() -> tuple[bool, str]:
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        return True, OK
    except Exception as exc:
        return False, str(exc)[:200]


async def _check_redis() -> tuple[bool, str]:
    try:
        await get_redis().ping()
        return True, OK
    except Exception as exc:
        return False, str(exc)[:200]


async def _check_ibsng() -> tuple[bool, str]:
    from app.services.ibsng.client import IBSngClient

    try:
        async with IBSngClient() as client:
            groups = await client.list_groups()
        return True, f"{len(groups)} group(s)"
    except Exception as exc:
        return False, str(exc)[:200]


async def _check_plisio() -> tuple[bool, str]:
    from app.services.payments.plisio import PaymentProviderNotConfiguredError, list_currencies

    try:
        coins = await list_currencies()
        return True, f"{len(coins)} coin(s)"
    except PaymentProviderNotConfiguredError:
        # Not configured is not unhealthy: the bot is designed to run
        # with crypto visibly unavailable.
        return True, "not configured"
    except Exception as exc:
        return False, str(exc)[:200]


CHECKS = {
    "Database": _check_database,
    "Redis": _check_redis,
    "IBSng": _check_ibsng,
    "Plisio": _check_plisio,
}


async def check_all() -> dict[str, tuple[bool, str]]:
    results: dict[str, tuple[bool, str]] = {}
    for name, check in CHECKS.items():
        try:
            results[name] = await check()
        except Exception as exc:  # a check must never take down the loop
            logger.exception("Health check %s raised", name)
            results[name] = (False, str(exc)[:200])
    return results


async def _previous_state(component: str) -> str | None:
    try:
        return await get_redis().get(_STATE_KEY.format(component=component))
    except RedisError:
        return None


async def _store_state(component: str, healthy: bool) -> None:
    try:
        await get_redis().set(_STATE_KEY.format(component=component), OK if healthy else "fail")
    except RedisError:
        logger.warning("Could not store health state for %s", component)


async def _heartbeat_due() -> bool:
    try:
        redis = get_redis()
        if await redis.get(_HEARTBEAT_KEY):
            return False
        await redis.set(_HEARTBEAT_KEY, "1", ex=HEARTBEAT_INTERVAL_SECONDS)
        return True
    except RedisError:
        return False


async def run_health_check(bot: Bot) -> dict[str, tuple[bool, str]]:
    """One pass. Posts only what changed, plus at most a daily summary."""
    results = await check_all()

    for component, (healthy, detail) in results.items():
        previous = await _previous_state(component)
        current = OK if healthy else "fail"
        if previous == current:
            continue
        await _store_state(component, healthy)
        if previous is None and healthy:
            # First sighting of a healthy component is not news.
            continue
        await log_event(
            bot,
            HEALTH_OK if healthy else HEALTH_ALERT,
            Component=component,
            Detail=detail,
        )

    if await _heartbeat_due():
        summary = " · ".join(
            f"{name} {'ok' if healthy else 'FAIL'}" for name, (healthy, _) in results.items()
        )
        all_ok = all(healthy for healthy, _ in results.values())
        await log_event(bot, HEALTH_OK if all_ok else HEALTH_ALERT, Checks=summary)

    return results


async def run_health_loop(bot: Bot) -> None:
    while True:
        try:
            await run_health_check(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Health loop pass failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
