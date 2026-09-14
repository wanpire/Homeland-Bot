from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.db.session import async_session_maker
from app.services.bot_users import record_seen


class UserTrackingMiddleware(BaseMiddleware):
    """Records every distinct telegram_id that ever interacts with the
    bot, for the admin broadcast feature's recipient list."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is not None and inner.from_user is not None:
            async with async_session_maker() as session:
                await record_seen(session, inner.from_user.id, inner.from_user.username)

        return await handler(event, data)
