from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.bot.keyboards.mandatory_channel import join_channels_keyboard
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.mandatory_channel import get_mandatory_channels, is_mandatory_channel_enabled

logger = logging.getLogger(__name__)

_JOINED_STATUSES = {"member", "administrator", "creator", "restricted"}
_JOIN_PROMPT_TEXT = (
    "📢 <b>Join our channel to continue</b>\n\n"
    "Please join the channel(s) below, then tap \"I've Joined\"."
)


class MandatoryChannelMiddleware(BaseMiddleware):
    """Blocks every interaction for a non-member of the configured
    channel(s), when the feature is enabled. Admins are always exempt -
    a misconfigured channel must never lock the admin panel itself. A
    channel membership check that itself fails (bot not an admin of
    that channel, transient API error) fails OPEN - a broken config
    must never take down the whole bot for every user."""

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
            if not await is_mandatory_channel_enabled(session):
                return await handler(event, data)
            channels = await get_mandatory_channels(session)
            if not channels:
                return await handler(event, data)

        missing = [username for username in channels if not await self._is_member(inner, user_id, username)]
        if not missing:
            return await handler(event, data)

        keyboard = join_channels_keyboard(missing)
        if isinstance(inner, CallbackQuery):
            if inner.message is not None:
                await inner.message.edit_text(_JOIN_PROMPT_TEXT, reply_markup=keyboard)
            await inner.answer()
        else:
            await inner.answer(_JOIN_PROMPT_TEXT, reply_markup=keyboard)
        return None

    @staticmethod
    async def _is_member(inner: Message | CallbackQuery, user_id: int, username: str) -> bool:
        try:
            member = await inner.bot.get_chat_member(chat_id=f"@{username}", user_id=user_id)
        except TelegramAPIError as exc:
            logger.warning("Mandatory channel check failed for @%s: %s - failing open", username, exc)
            return True
        return member.status in _JOINED_STATUSES
