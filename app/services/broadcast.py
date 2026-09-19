"""The one outbound mass-messaging pipeline, shared by the admin
Announcement flow and the Ad Campaign flow (app/bot/handlers/broadcast.py
and campaign.py). Recipient rules, pacing, failure accounting and the
summary DM all live here so the two flows can never drift apart."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser
from app.db.session import async_session_maker
from app.i18n.texts import DEFAULT_LANG

logger = logging.getLogger(__name__)

Content = dict[str, Any]
KeyboardFor = Callable[[str], InlineKeyboardMarkup | None]

_SEND_DELAY_SECONDS = 0.05

# asyncio.create_task() only leaves the task referenced by the event
# loop's internal *weak* set - with nothing else keeping it alive, the
# task can be garbage-collected mid-run in a long-lived polling process,
# silently truncating a broadcast with no error and no summary DM. This
# set holds a strong reference to every in-flight task; the done-callback
# discards it once the task finishes (success or not), so it doesn't leak.
_background_tasks: set[asyncio.Task[None]] = set()


async def list_recipients(session: AsyncSession, *, exclude_telegram_id: int) -> list[tuple[int, str]]:
    """(telegram_id, lang) for every tracked, unblocked bot user except the
    admin running the send - UserTrackingMiddleware records the admin's
    own interaction too, so without excluding them they'd receive their
    own announcement (and its summary) as if they were a recipient.
    Blocked users (BotUser.is_blocked) are excluded too: BlockedUserMiddleware
    stops them from interacting with the bot, but nothing stops the bot
    from messaging them unless this query does. A user who never picked a
    language gets DEFAULT_LANG, the same fallback app/services/reminders.py
    uses."""
    result = await session.execute(
        select(BotUser.telegram_id, BotUser.language).where(
            BotUser.is_blocked.is_(False),
            BotUser.telegram_id != exclude_telegram_id,
        )
    )
    return [(row[0], row[1] or DEFAULT_LANG) for row in result.all()]


async def run_broadcast(
    bot: Bot,
    admin_telegram_id: int,
    content: Content,
    *,
    keyboard_for: KeyboardFor | None = None,
    summary_label: str = "Broadcast",
) -> None:
    async with async_session_maker() as session:
        recipients = await list_recipients(session, exclude_telegram_id=admin_telegram_id)

    sent, failed = 0, 0
    for telegram_id, lang in recipients:
        reply_markup = keyboard_for(lang) if keyboard_for is not None else None
        try:
            if content["kind"] == "text":
                await bot.send_message(telegram_id, content["text"], reply_markup=reply_markup)
            elif content["kind"] == "photo":
                await bot.send_photo(
                    telegram_id, content["file_id"], caption=content["caption"] or None, reply_markup=reply_markup
                )
            else:
                await bot.send_document(
                    telegram_id, content["file_id"], caption=content["caption"] or None, reply_markup=reply_markup
                )
            sent += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(_SEND_DELAY_SECONDS)

    try:
        await bot.send_message(admin_telegram_id, f"✅ {summary_label} done — sent: {sent}, failed: {failed}.")
    except TelegramAPIError:
        logger.exception(
            "Could not deliver %s summary to admin telegram_id=%s", summary_label.lower(), admin_telegram_id
        )


def start_broadcast_task(
    bot: Bot,
    admin_telegram_id: int,
    content: Content,
    *,
    keyboard_for: KeyboardFor | None = None,
    summary_label: str = "Broadcast",
) -> asyncio.Task[None]:
    task = asyncio.create_task(
        run_broadcast(bot, admin_telegram_id, content, keyboard_for=keyboard_for, summary_label=summary_label)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
