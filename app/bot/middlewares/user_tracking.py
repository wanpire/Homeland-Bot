from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.db.session import async_session_maker
from app.services.adminlog import NEW_USER, log_event
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
                created = await record_seen(session, inner.from_user.id, inner.from_user.username)
            if created:
                # Only the first interaction: this middleware runs on
                # every update, and log_event never raises, so a logging
                # problem cannot block the update.
                user = inner.from_user
                who = f"@{user.username} ({user.id})" if user.username else str(user.id)
                await log_event(data["bot"], NEW_USER, User=who, Language=user.language_code)

        return await handler(event, data)
