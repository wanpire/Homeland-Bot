"""Shared pytest fixtures. Everything here runs against fully isolated
test infrastructure: a disposable Postgres (db_test), a disposable
Redis (redis_test), an in-process fake IBSng XML-RPC server, and an
in-process fake Telegram Bot session that never makes a real HTTP call.

Required env vars (set by docker-compose.test.yml's test-runner
service) must be present BEFORE any `app.*` module is imported, since
app.config.get_settings() is @lru_cache'd and app.db.session builds its
engine at import time."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import pytest_asyncio

_REQUIRED_TEST_ENV = {
    "BOT_TOKEN": "123456:TEST-TOKEN-NEVER-SENT-TO-REAL-TELEGRAM",
    "ADMIN_IDS": "111111111",
    "IBSNG_BASE_URL": "http://127.0.0.1:8765",
    "IBSNG_USERNAME": "test",
    "IBSNG_PASSWORD": "test",
    "IBSNG_ISP_NAME": "test-isp",
    "IBSNG_AUTH_REMOTEADDR": "127.0.0.1",
    "ENVIRONMENT": "test",
    "LOG_LEVEL": "WARNING",
}
for _key, _default in _REQUIRED_TEST_ENV.items():
    os.environ.setdefault(_key, _default)

if os.environ.get("POSTGRES_DB", "homeland") == "homeland" and os.environ.get("ENVIRONMENT") == "test":
    raise RuntimeError(
        "Refusing to run tests: POSTGRES_DB looks like the production database name. "
        "Run tests via docker-compose.test.yml (make test), which points at a disposable "
        "homeland_test database instead."
    )

from tests.fakes.fake_bot_session import FakeBotSession  # noqa: E402
from tests.fakes.fake_ibsng_server import FakeIBSngServer  # noqa: E402
from tests.factories import FAKE_ADMIN_ID  # noqa: E402,F401


@pytest.fixture(scope="session")
def ibsng_server() -> Generator[FakeIBSngServer, None, None]:
    server = FakeIBSngServer(port=8765)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_database(ibsng_server: FakeIBSngServer) -> Generator[None, None, None]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_database() -> AsyncGenerator[None, None]:
    from app.db.base import Base
    from app.db.session import engine
    from sqlalchemy import text

    table_names = [t.name for t in Base.metadata.sorted_tables]
    async with engine.begin() as conn:
        if table_names:
            await conn.execute(text(f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis() -> AsyncGenerator[None, None]:
    from app.redis import get_redis

    client = get_redis()
    await client.flushdb()
    await client.aclose()
    yield


@pytest.fixture(autouse=True)
def _reset_ibsng(ibsng_server: FakeIBSngServer) -> Generator[None, None, None]:
    ibsng_server.reset()
    yield


@pytest.fixture
def fake_session() -> FakeBotSession:
    return FakeBotSession()


@pytest.fixture
def bot(fake_session: FakeBotSession) -> Any:  # aiogram.Bot type is complex; we use Any for clarity
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    return Bot(
        token=os.environ["BOT_TOKEN"],
        session=fake_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest_asyncio.fixture(scope="session")
async def dispatcher() -> Any:  # aiogram.Dispatcher type is complex; we use Any for clarity
    """The real Dispatcher, wired like app.main.main() does - built out
    incrementally as later tasks add routers/middlewares (Task 8 adds
    the first ones). Session-scoped: aiogram Router objects are
    module-level singletons and refuse to attach to more than one
    Dispatcher. Safe to share across the whole session because every
    test uses a distinct telegram_id."""
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    dp = Dispatcher(storage=MemoryStorage())
    return dp
