"""Helpers for constructing real aiogram Update/Message/CallbackQuery
objects, and for seeding the minimal DB rows each functional test
needs."""

from __future__ import annotations

import datetime as dt
import itertools

from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy.ext.asyncio import AsyncSession

_update_id_counter = itertools.count(1)
_message_id_counter = itertools.count(10_000)

FAKE_ADMIN_ID = 111111111  # matches ADMIN_IDS in conftest.py's test env


def make_user(telegram_id: int, *, username: str | None = None, first_name: str = "Test") -> User:
    return User(id=telegram_id, is_bot=False, first_name=first_name, username=username)


def make_message(telegram_id: int, text: str | None = None, *, username: str | None = None) -> Message:
    return Message(
        message_id=next(_message_id_counter),
        date=dt.datetime.now(dt.timezone.utc),
        chat=Chat(id=telegram_id, type="private"),
        from_user=make_user(telegram_id, username=username),
        text=text,
    )


def make_message_update(telegram_id: int, text: str | None = None, *, username: str | None = None) -> Update:
    return Update(update_id=next(_update_id_counter), message=make_message(telegram_id, text, username=username))


def make_group_message_update(
    telegram_id: int,
    text: str | None = None,
    *,
    chat_id: int | None = None,
    username: str | None = None,
) -> Update:
    """A message sent in a group chat rather than a DM - the exact shape
    PrivateChatOnlyMiddleware exists to drop."""
    return Update(
        update_id=next(_update_id_counter),
        message=Message(
            message_id=next(_message_id_counter),
            date=dt.datetime.now(dt.timezone.utc),
            chat=Chat(id=chat_id if chat_id is not None else -telegram_id, type="group"),
            from_user=make_user(telegram_id, username=username),
            text=text,
        ),
    )


def make_callback_update(
    telegram_id: int, data: str, *, anchor_message: Message | None = None, username: str | None = None
) -> Update:
    message = anchor_message or make_message(telegram_id, "(anchor)", username=username)
    callback = CallbackQuery(
        id=str(next(_update_id_counter)),
        from_user=make_user(telegram_id, username=username),
        chat_instance="test-chat-instance",
        data=data,
        message=message,
    )
    return Update(update_id=next(_update_id_counter), callback_query=callback)


def make_photo_message(telegram_id: int, *, file_id: str, username: str | None = None) -> Message:
    from aiogram.types import PhotoSize

    return Message(
        message_id=next(_message_id_counter),
        date=dt.datetime.now(dt.timezone.utc),
        chat=Chat(id=telegram_id, type="private"),
        from_user=make_user(telegram_id, username=username),
        photo=[PhotoSize(file_id=file_id, file_unique_id=f"{file_id}-unique", width=100, height=100)],
    )


def make_photo_message_update(telegram_id: int, *, file_id: str, username: str | None = None) -> Update:
    return Update(update_id=next(_update_id_counter), message=make_photo_message(telegram_id, file_id=file_id, username=username))


async def seed_bot_user(session: AsyncSession, telegram_id: int, *, username: str | None = None) -> None:
    from app.db.models.bot_user import BotUser

    session.add(BotUser(telegram_id=telegram_id, username=username))
    await session.commit()
