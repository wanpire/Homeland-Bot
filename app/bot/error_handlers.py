"""Global aiogram error handler - registered once in main.py via
dp.errors.register(...). Handles a DB connection-pool timeout with a
clear message instead of the unhandled-exception path every other
error still takes."""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

logger = logging.getLogger(__name__)

_POOL_BUSY_MESSAGE = "⏳ The server is temporarily busy. Please try again shortly."


async def handle_pool_timeout(event: ErrorEvent) -> bool:
    if not isinstance(event.exception, PoolTimeoutError):
        return False

    inner: Message | CallbackQuery | None = event.update.message or event.update.callback_query
    chat_id = None
    if isinstance(inner, Message):
        chat_id = inner.chat.id
    elif isinstance(inner, CallbackQuery) and inner.message is not None:
        chat_id = inner.message.chat.id

    logger.warning("DB connection pool exhausted (update_id=%s, chat_id=%s)", event.update.update_id, chat_id)

    if chat_id is not None:
        try:
            await event.update.bot.send_message(chat_id, _POOL_BUSY_MESSAGE)
        except Exception:
            logger.exception("Could not deliver the pool-busy message to chat_id=%s", chat_id)
    return True
