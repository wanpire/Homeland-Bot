"""The operational log group: one format, one sender.

Every entry looks the same shape so an admin scrolling the group can
sort by the first line alone - a distinct emoji and upper-case title per
category, then that category's fields always in the same order.

No caller anywhere composes a log message or calls bot.send_message for
logging. Adding a category later is one entry in EVENTS plus one call
site, which is the whole point of the indirection.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventType:
    key: str
    emoji: str
    title: str
    #: The order fields are printed in. A value not listed here is never
    #: printed, so a typo at a call site cannot silently reshape an entry.
    fields: tuple[str, ...]


NEW_USER = "new_user"
PURCHASE = "purchase"
RENEWAL = "renewal"
TRIAL = "trial"
HEALTH_OK = "health_ok"
HEALTH_ALERT = "health_alert"
BACKUP = "backup"

EVENTS: dict[str, EventType] = {
    NEW_USER: EventType(NEW_USER, "🆕", "NEW USER", ("User", "Language")),
    PURCHASE: EventType(PURCHASE, "💰", "PURCHASE", ("User", "Plan", "Amount", "Provider", "Account")),
    RENEWAL: EventType(RENEWAL, "♻️", "RENEWAL", ("User", "Plan", "Amount", "Provider", "Account")),
    TRIAL: EventType(TRIAL, "🎁", "TRIAL", ("User", "Plan", "Account")),
    HEALTH_OK: EventType(HEALTH_OK, "💚", "HEALTH OK", ("Component", "Detail", "Checks")),
    HEALTH_ALERT: EventType(HEALTH_ALERT, "🔴", "HEALTH ALERT", ("Component", "Detail", "Checks")),
    BACKUP: EventType(BACKUP, "💾", "BACKUP", ("Status", "File", "Size", "Kept", "Duration", "Error")),
}


def render_event(key: str, values: dict[str, object], *, now: dt.datetime | None = None) -> str:
    """The rendered entry. Separated from sending so a test can read it
    without a Bot, and so the format is provable in isolation."""
    event = EVENTS[key]
    moment = now or dt.datetime.now(dt.timezone.utc)

    lines = [f"{event.emoji} <b>{event.title}</b>"]
    for field in event.fields:
        value = values.get(field)
        # An absent field is omitted rather than printed blank: a column
        # of "Detail: " lines is exactly the noise this format avoids.
        if value is None or value == "":
            continue
        lines.append(f"{field}: {html.escape(str(value))}")
    lines.append(f"Time: {moment:%Y-%m-%d %H:%M} UTC")
    return "\n".join(lines)


async def log_event(bot: Bot, key: str, **values: object) -> None:
    """Post one entry. Never raises.

    Logging is observation, not a step in any transaction: a
    misconfigured chat id, the bot removed from the group, or Telegram
    being down must never fail a purchase, a trial, or a health check."""
    chat_id = get_settings().admin_log_chat_id.strip()
    if not chat_id:
        # Unset means the feature is off, which keeps it opt-in and
        # leaves local runs and the test suite untouched.
        return
    if key not in EVENTS:
        logger.error("Unknown admin log event %r - not sent", key)
        return

    try:
        await bot.send_message(int(chat_id), render_event(key, values))
    except ValueError:
        logger.error("ADMIN_LOG_CHAT_ID is not a valid chat id: %r", chat_id)
    except TelegramAPIError as exc:
        logger.error("Could not post %s to the admin log group: %s", key, exc)
    except Exception:
        logger.exception("Unexpected failure posting %s to the admin log group", key)
