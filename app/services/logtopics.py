"""Forum-topic routing for the operational log group.

Thread ids are discovered at runtime and stored in the existing
app_config key/value table, never hardcoded: a group rebuilt from
scratch, or a topic deleted by hand, must be recoverable by running the
setup again rather than by editing code.

If a topic cannot be created, the entry still goes to the group's
general thread. A log entry is never lost because its filing cabinet is
missing.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.db.session import async_session_maker
from app.services.app_config import get_config, set_config

logger = logging.getLogger(__name__)

_KEY = "log_topic:{category}"


async def _stored_thread_id(category: str) -> int | None:
    async with async_session_maker() as session:
        raw = await get_config(session, _KEY.format(category=category))
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Stored thread id for %s is not a number: %r", category, raw)
        return None


async def _store_thread_id(category: str, thread_id: int) -> None:
    async with async_session_maker() as session:
        await set_config(session, _KEY.format(category=category), str(thread_id))


async def resolve_thread_id(bot: Bot, chat_id: int, category: str, topic_name: str) -> int | None:
    """The thread to file this category under, creating the topic the
    first time. None means "use the general thread", which is what
    happens when the chat is not a forum or creation failed."""
    existing = await _stored_thread_id(category)
    if existing is not None:
        return existing

    try:
        topic = await bot.create_forum_topic(chat_id=chat_id, name=topic_name)
    except TelegramAPIError as exc:
        # Not a forum, missing can_manage_topics, or Telegram refusing:
        # fall back rather than dropping the entry.
        logger.warning("Could not create the %s topic (%s) - using the general thread", category, exc)
        return None

    await _store_thread_id(category, topic.message_thread_id)
    logger.info("Created log topic %s (%s) -> thread %s", topic_name, category, topic.message_thread_id)
    return topic.message_thread_id


async def ensure_all_topics(bot: Bot, chat_id: int) -> dict[str, str]:
    """Create every category's topic that does not exist yet. Returns a
    category -> outcome map for the /logtopics report."""
    from app.services.adminlog import EVENTS

    outcomes: dict[str, str] = {}
    seen: set[str] = set()
    for event in EVENTS.values():
        if event.topic in seen:
            continue
        seen.add(event.topic)

        if await _stored_thread_id(event.topic) is not None:
            outcomes[event.topic_name] = "already set up"
            continue
        thread_id = await resolve_thread_id(bot, chat_id, event.topic, event.topic_name)
        outcomes[event.topic_name] = f"created (thread {thread_id})" if thread_id else "failed"
    return outcomes
