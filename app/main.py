import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from aiohttp import web

from app.bot.error_handlers import handle_pool_timeout
from app.bot.handlers import (
    admin, admin_admins, admin_block, admin_discounts, admin_fallback, admin_renew, admin_settings,
    broadcast, buy, campaign, fallback, financial, myservices, openvpn_setup, renew, trial,
    reports, tutorial_admin, tutorials, user_admin, users,
)
from app.bot.middlewares.blocked_user import BlockedUserMiddleware
from app.bot.middlewares.language import LanguageMiddleware
from app.bot.middlewares.mandatory_channel import MandatoryChannelMiddleware
from app.bot.middlewares.private_chat_only import PrivateChatOnlyMiddleware
from app.bot.middlewares.user_tracking import UserTrackingMiddleware
from app.config import get_settings
from app.logging_setup import install_secret_redaction
from app.services.payments.reconcile import run_reconcile_loop
from app.services.reminders import run_reminder_loop
from app.webhook import create_webhook_app

settings = get_settings()

logging.basicConfig(level=settings.log_level)
# Installed immediately after basicConfig and before any client runs:
# httpx logs full request URLs at INFO, and Plisio's secret key travels
# as a query parameter, so without this the live key lands in the logs.
install_secret_redaction([settings.plisio_secret_key, settings.bot_token])
logger = logging.getLogger(__name__)


def build_dispatcher(storage: BaseStorage) -> Dispatcher:
    """The single source of truth for how the Dispatcher is wired.

    Both production (main(), with RedisStorage) and the test suite
    (tests/conftest.py's `dispatcher` fixture, with MemoryStorage) call
    this, so the two can never drift apart - which is exactly how the
    global error handler previously shipped without a single test ever
    registering it."""
    dp = Dispatcher(storage=storage)
    dp.errors.register(handle_pool_timeout)
    dp.update.outer_middleware(PrivateChatOnlyMiddleware())
    dp.update.outer_middleware(UserTrackingMiddleware())
    # BlockedUserMiddleware MUST run before LanguageMiddleware: a blocked
    # user with language still unset (every currently-blocked user, since
    # there's no backfill) would otherwise be intercepted by the language
    # chooser on every message forever, never reaching BlockedUserMiddleware
    # and never seeing the "you are blocked" message. A deliberate,
    # reviewed deviation from the original design spec's stated order
    # (Language right after UserTracking) - the menu:language/lang:set:*
    # bypass semantics inside LanguageMiddleware are unaffected by this
    # reordering.
    dp.update.outer_middleware(BlockedUserMiddleware())
    dp.update.outer_middleware(LanguageMiddleware())
    dp.update.outer_middleware(MandatoryChannelMiddleware())

    dp.include_router(admin.router)
    dp.include_router(admin_admins.router)
    dp.include_router(admin_block.router)
    dp.include_router(admin_discounts.router)
    dp.include_router(admin_renew.router)
    dp.include_router(admin_settings.router)
    dp.include_router(financial.router)
    dp.include_router(user_admin.router)
    dp.include_router(reports.router)
    dp.include_router(broadcast.router)
    dp.include_router(campaign.router)
    # MUST stay after every adm:*-handling router above (admin,
    # admin_admins, admin_block, admin_discounts, admin_renew,
    # admin_settings, broadcast, campaign) - it claims any adm:* callback none of
    # them matched, so registering it earlier would shadow a legitimate
    # handler. The routers below it never claim adm:* data.
    dp.include_router(admin_fallback.router)
    dp.include_router(buy.router)
    dp.include_router(renew.router)
    dp.include_router(myservices.router)
    dp.include_router(tutorials.router)
    dp.include_router(openvpn_setup.router)
    dp.include_router(users.router)
    dp.include_router(trial.router)
    dp.include_router(tutorial_admin.router)
    dp.include_router(fallback.router)
    return dp


async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = RedisStorage.from_url(settings.redis_url)
    dp = build_dispatcher(storage)

    # /admintutorials is listed for everyone rather than scoped to an
    # admin-only BotCommandScope: the admin list lives in the database
    # (app/services/admin_users.py), not in config, so there is no
    # static chat-id list to build a per-chat scope from at startup.
    # The handler itself is gated by has_level(), so a non-admin seeing
    # it in autocomplete just gets no response - the same trade-off the
    # main menu's admin button already makes.
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Start / main menu"),
            BotCommand(command="admintutorials", description="Admin: upload tutorials/profiles"),
        ]
    )
    await bot.delete_webhook(drop_pending_updates=True)

    runner = web.AppRunner(create_webhook_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()
    logger.info("Webhook server listening on :%s", settings.webhook_port)

    reminder_task = asyncio.create_task(run_reminder_loop(bot))
    # Finishes any paid invoice whose activation failed while IBSng was
    # unreachable, after Plisio has given up retrying its callback.
    reconcile_task = asyncio.create_task(run_reconcile_loop(bot))

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        reconcile_task.cancel()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
