import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand

from app.bot.error_handlers import handle_pool_timeout
from app.bot.handlers import fallback, trial, users
from app.bot.middlewares.blocked_user import BlockedUserMiddleware
from app.bot.middlewares.private_chat_only import PrivateChatOnlyMiddleware
from app.bot.middlewares.user_tracking import UserTrackingMiddleware
from app.config import get_settings

settings = get_settings()

logging.basicConfig(level=settings.log_level)
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
    dp.update.outer_middleware(BlockedUserMiddleware())

    dp.include_router(users.router)
    dp.include_router(trial.router)
    dp.include_router(fallback.router)
    return dp


async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = RedisStorage.from_url(settings.redis_url)
    dp = build_dispatcher(storage)

    await bot.set_my_commands([BotCommand(command="start", description="Start / main menu")])
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
