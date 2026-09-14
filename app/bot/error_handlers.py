"""Global aiogram error handler - registered once in main.py via
dp.errors.register(...). Handles a DB connection-pool timeout with a
clear message instead of the unhandled-exception path every other
error still takes.

Anything that is NOT a pool timeout must return the UNHANDLED sentinel,
not a falsy value: aiogram's ErrorsMiddleware only re-raises the original
exception when the error handler's response `is UNHANDLED`. Returning
False here would mark every bug in every handler as "handled" and
discard it silently, with no traceback anywhere."""

from __future__ import annotations

import logging
from typing import Any

from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

logger = logging.getLogger(__name__)

_POOL_BUSY_MESSAGE = "⏳ The server is temporarily busy. Please try again shortly."


async def handle_pool_timeout(event: ErrorEvent) -> Any:
    if not isinstance(event.exception, PoolTimeoutError):
        return UNHANDLED

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
