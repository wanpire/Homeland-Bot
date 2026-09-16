from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.db.session import async_session_maker
from app.services.admin_users import has_level


class IsSalesAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        async with async_session_maker() as session:
            return await has_level(session, user.id, "sales")


class IsFullAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        async with async_session_maker() as session:
            return await has_level(session, user.id, "full")
