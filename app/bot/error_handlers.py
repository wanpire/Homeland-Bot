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

from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.bot_users import get_language

logger = logging.getLogger(__name__)


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
        # chat_id == telegram_id is safe here: PrivateChatOnlyMiddleware
        # already guarantees every update reaching this handler is a 1:1 DM.
        try:
            async with async_session_maker() as session:
                lang = (await get_language(session, chat_id)) or "en"
        except Exception:
            logger.warning("Language lookup failed for chat_id=%s, defaulting to English", chat_id)
            lang = "en"
        try:
            await event.update.bot.send_message(chat_id, t("pool_busy", lang))
        except Exception:
            logger.exception("Could not deliver the pool-busy message to chat_id=%s", chat_id)
    return True
