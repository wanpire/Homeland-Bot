from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject, Update


class PrivateChatOnlyMiddleware(BaseMiddleware):
    """Drops every incoming update that isn't from a private chat with
    the bot - Homeland is DM-only. Registered first, before every other
    outer middleware."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is None:
            return await handler(event, data)

        if isinstance(inner, CallbackQuery):
            # aiogram types CallbackQuery.message as Message |
            # InaccessibleMessage | None. When it is None there is no chat
            # to gate on at all, so drop the update like any other
            # un-gatable case rather than AttributeError-ing on .chat.
            if inner.message is None:
                return None
            chat = inner.message.chat
        else:
            chat = inner.chat

        if chat.type != ChatType.PRIVATE:
            return None

        return await handler(event, data)
