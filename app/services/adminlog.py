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
    #: Which forum topic this category files under. Several event types
    #: can share a topic (health ok and health alert both belong in the
    #: health thread); the thread id itself is discovered at runtime,
    #: never hardcoded - see app/services/logtopics.py.
    topic: str = "general"
    topic_name: str = "General"


NEW_USER = "new_user"
PURCHASE = "purchase"
RENEWAL = "renewal"
TRIAL = "trial"
HEALTH_OK = "health_ok"
HEALTH_ALERT = "health_alert"
SERVER_HEALTH = "server_health"
SERVER_HEALTH_ALERT = "server_health_alert"
BACKUP = "backup"
ACCOUNTING = "accounting"

#: Topic keys. Several event types share one (an ok and an alert belong
#: in the same thread), which is why the topic is its own field.
TOPIC_NEW_USER = "new_user"
TOPIC_PURCHASE = "purchase"
TOPIC_RENEWAL = "renewal"
TOPIC_TRIAL = "trial"
TOPIC_BACKUP = "backup"
TOPIC_SERVER = "server_health"
TOPIC_SERVICE = "service_health"
TOPIC_ACCOUNTING = "accounting"

_HEALTH_FIELDS = ("Component", "Detail", "Checks")
_PAYMENT_FIELDS = ("User", "Plan", "Amount", "Provider", "Account")

EVENTS: dict[str, EventType] = {
    NEW_USER: EventType(NEW_USER, "🆕", "NEW USER", ("User", "Language"), TOPIC_NEW_USER, "🆕 New Users"),
    PURCHASE: EventType(PURCHASE, "💰", "PURCHASE", _PAYMENT_FIELDS, TOPIC_PURCHASE, "💰 Purchases"),
    RENEWAL: EventType(RENEWAL, "♻️", "RENEWAL", _PAYMENT_FIELDS, TOPIC_RENEWAL, "♻️ Renewals"),
    TRIAL: EventType(TRIAL, "🎁", "TRIAL", ("User", "Plan", "Account"), TOPIC_TRIAL, "🎁 Trials"),
    HEALTH_OK: EventType(HEALTH_OK, "💚", "SERVICE OK", _HEALTH_FIELDS, TOPIC_SERVICE, "🩺 Service Health"),
    HEALTH_ALERT: EventType(HEALTH_ALERT, "🔴", "SERVICE ALERT", _HEALTH_FIELDS, TOPIC_SERVICE, "🩺 Service Health"),
    SERVER_HEALTH: EventType(
        SERVER_HEALTH, "🖥", "SERVER OK", ("Disk", "Memory", "Load", "Uptime"), TOPIC_SERVER, "🖥 Server Health"
    ),
    SERVER_HEALTH_ALERT: EventType(
        SERVER_HEALTH_ALERT, "🟠", "SERVER ALERT", ("Disk", "Memory", "Load", "Uptime", "Detail"),
        TOPIC_SERVER, "🖥 Server Health",
    ),
    BACKUP: EventType(
        BACKUP, "💾", "BACKUP", ("Status", "File", "Size", "Kept", "Duration", "Error"), TOPIC_BACKUP, "💾 Backups"
    ),
    ACCOUNTING: EventType(
        ACCOUNTING, "📊", "ACCOUNTING", ("Period", "Revenue", "Orders", "Average", "Discounts", "Providers"),
        TOPIC_ACCOUNTING, "📊 Accounting",
    ),
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
        target = int(chat_id)
    except ValueError:
        logger.error("ADMIN_LOG_CHAT_ID is not a valid chat id: %r", chat_id)
        return

    # Resolved per send rather than cached in memory: the id lives in
    # app_config, so a topic recreated by /logtopics takes effect without
    # a restart.
    from app.services.logtopics import resolve_thread_id

    event = EVENTS[key]
    thread_id = await resolve_thread_id(bot, target, event.topic, event.topic_name)

    try:
        await bot.send_message(target, render_event(key, values), message_thread_id=thread_id)
    except ValueError:
        logger.error("ADMIN_LOG_CHAT_ID is not a valid chat id: %r", chat_id)
    except TelegramAPIError as exc:
        logger.error("Could not post %s to the admin log group: %s", key, exc)
    except Exception:
        logger.exception("Unexpected failure posting %s to the admin log group", key)
