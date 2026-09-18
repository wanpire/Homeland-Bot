from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.app_config import get_config
from app.services.bot_users import get_language
from app.services.ibsng.client import IBSngClient
from app.services.vpn_users import get_service_status

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 30 * 60
DEFAULT_DAYS_BEFORE = 2  # public: app/bot/handlers/admin_settings.py's status screen shares this default


def _renew_now_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("renew_now_button", lang), callback_data="menu:renew")
    builder.adjust(1)
    return builder.as_markup()


async def _reminder_window(session: AsyncSession) -> dt.timedelta:
    raw = await get_config(session, "reminder_days_before")
    try:
        days = int(raw) if raw else DEFAULT_DAYS_BEFORE
    except ValueError:
        days = DEFAULT_DAYS_BEFORE
    # Clamp to a sane range: a validated-but-absurd admin input (e.g.
    # 10**12) would otherwise reach dt.timedelta(days=...) and raise
    # OverflowError, silently killing every future pass of the job.
    return dt.timedelta(days=min(max(days, 1), 365))


async def send_due_reminders(bot: Bot) -> None:
    """One pass: for every non-trial, non-blocked VPNUser not yet reminded
    this cycle, ask IBSng for its live expiry and send the reminder if it
    falls within the admin-configured window. get_service_status only
    catches IBSngError internally - any other exception (malformed
    XML-RPC response, unexpected payload shape, ...) propagates, so each
    candidate's lookup is wrapped in its own try/except below; that is
    what isolates one bad row from aborting the rest of the batch, not
    get_service_status itself. Safe to call repeatedly -
    expiry_reminder_sent_at (cleared on renewal by renew_and_change_group)
    makes it idempotent per expiry cycle. An "expired" candidate gets
    stamped without a message, so an account that lapses without ever
    getting a reminder sent doesn't stay a permanent candidate re-queried
    forever. Trial accounts are excluded - they aren't renewable, so a
    "renew via the bot" reminder wouldn't make sense for them. Blocked
    users are excluded too, matching the same rule broadcast.py's
    _list_broadcast_recipients established for outbound messaging."""
    async with async_session_maker() as session:
        enabled_raw = await get_config(session, "reminder_enabled")
        if enabled_raw == "false":
            return

        window = await _reminder_window(session)

        candidates = (
            await session.execute(
                select(VPNUser).where(
                    VPNUser.expiry_reminder_sent_at.is_(None),
                    VPNUser.is_trial.is_(False),
                    ~select(BotUser.id)
                    .where(BotUser.telegram_id == VPNUser.telegram_id, BotUser.is_blocked.is_(True))
                    .exists(),
                ).order_by(VPNUser.id)
            )
        ).scalars().all()
        if not candidates:
            return

        now = dt.datetime.now(dt.timezone.utc)
        async with IBSngClient() as client:
            for vpn_user in candidates:
                try:
                    status, expiry = await get_service_status(client, vpn_user.ibsng_username)
                except Exception:
                    logger.exception(
                        "Failed to look up IBSng status for ibsng_username=%s", vpn_user.ibsng_username
                    )
                    continue
                if status == "expired":
                    # Self-healing: renew_and_change_group clears this stamp
                    # back to None the moment the customer actually renews,
                    # so they immediately become eligible again. Without
                    # this, an account that lapses without ever getting a
                    # reminder sent (bot downtime, feature toggled off, a
                    # send failure) stays a permanent candidate, re-queried
                    # and re-looked-up against IBSng every pass forever.
                    vpn_user.expiry_reminder_sent_at = now
                    await session.commit()
                    continue
                if status != "active" or expiry is None:
                    continue
                if not (dt.timedelta(0) < (expiry - now) <= window):
                    continue

                try:
                    lang = (await get_language(session, vpn_user.telegram_id)) or "en"
                except Exception:
                    logger.exception(
                        "Failed to look up language for telegram_id=%s, defaulting to English",
                        vpn_user.telegram_id,
                    )
                    lang = "en"
                text = t("reminder_message", lang, username=vpn_user.ibsng_username, days=window.days)
                try:
                    await bot.send_message(vpn_user.telegram_id, text, reply_markup=_renew_now_keyboard(lang))
                except Exception:
                    logger.exception("Failed to send expiry reminder to telegram_id=%s", vpn_user.telegram_id)
                    continue
                vpn_user.expiry_reminder_sent_at = now
                await session.commit()


async def run_reminder_loop(bot: Bot) -> None:
    """Started as a background asyncio task from app/main.py - no
    scheduler library, matching AloBot's own proven pattern for this
    exact job (app/services/reminders.py in the sibling telegram-bot
    project)."""
    while True:
        try:
            await send_due_reminders(bot)
        except Exception:
            logger.exception("Reminder loop iteration failed")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
