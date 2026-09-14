from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.bot_users import is_blocked

_BLOCKED_MESSAGE = "⛔️ You have been blocked from using this bot."


class BlockedUserMiddleware(BaseMiddleware):
    """Blocks every interaction (including /start) for a telegram_id an
    admin flagged via block_user. Admins are always exempt so a block
    can never lock out the panel itself."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is None or inner.from_user is None:
            return await handler(event, data)

        user_id = inner.from_user.id
        async with async_session_maker() as session:
            if await has_level(session, user_id, "support"):
                return await handler(event, data)
            if not await is_blocked(session, user_id):
                return await handler(event, data)

        if isinstance(inner, CallbackQuery):
            await inner.answer(_BLOCKED_MESSAGE, show_alert=True)
        else:
            await inner.answer(_BLOCKED_MESSAGE)
        return None
