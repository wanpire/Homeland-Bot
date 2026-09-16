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

# Positive assertion, deliberately NOT conditioned on ENVIRONMENT: this
# suite runs `alembic downgrade base` (dropping every table) and TRUNCATEs
# before every single test. The only safe target is a disposable database
# whose name ends in "_test". Anything else - including the production
# default, which is exactly what `docker compose exec bot python -m pytest`
# would hand us - must abort before a single fixture runs.
_POSTGRES_DB = os.environ.get("POSTGRES_DB", "")
if not _POSTGRES_DB.endswith("_test"):
    raise RuntimeError(
        f"Refusing to run tests: POSTGRES_DB={_POSTGRES_DB!r} is not a disposable test "
        "database (its name must end in '_test'). This suite drops and truncates every "
        "table it points at. Run tests via docker-compose.test.yml (make test), which "
        "points at a disposable homeland_test database instead."
    )

from tests.fakes.fake_bot_session import FakeBotSession  # noqa: E402
from tests.fakes.fake_ibsng_server import FakeIBSngServer  # noqa: E402
from tests.factories import FAKE_ADMIN_ID  # noqa: E402,F401

# Side-effecting import: registers every model with Base.metadata, so
# Base.metadata.sorted_tables below knows about all tables. Deliberately
# not an explicit name list - that drifted (it was missing VPNUser).
import app.db.models  # noqa: E402,F401
from app.db.models.group import Group  # noqa: E402
from app.db.models.plan import Plan  # noqa: E402

# Columns re-inserted when restoring the catalog seed after a TRUNCATE.
# Derived from the models themselves, not hand-typed - a hand-typed list
# here already drifted once (it was missing `category` the first time
# that column was added), silently dropping it from every re-seeded row
# and reintroducing the exact NOT NULL failure that fix was meant to
# prevent. Server-generated columns (id, timestamps) are excluded since
# their values come from the DB, not from what the migration inserted.
_SERVER_MANAGED_COLUMNS = {"id", "created_at", "updated_at", "synced_at"}
_GROUP_SEED_COLUMNS = tuple(c.name for c in Group.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)
_PLAN_SEED_COLUMNS = tuple(c.name for c in Plan.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)

from app.db.models.tutorial_platform import TutorialPlatform  # noqa: E402
from app.db.models.tutorial_protocol import TutorialProtocol  # noqa: E402

_PLATFORM_SEED_COLUMNS = tuple(c.name for c in TutorialPlatform.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)
_PROTOCOL_SEED_COLUMNS = tuple(c.name for c in TutorialProtocol.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)


@pytest.fixture(scope="session")
def ibsng_server() -> Generator[FakeIBSngServer, None, None]:
    server = FakeIBSngServer(port=8765)
    server.start()
    yield server
    server.stop()


_BENIGN_DOWNGRADE_MARKERS = (
    "does not exist",  # psycopg/asyncpg UndefinedTable: nothing to downgrade yet
    "undefinedtable",
)


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_database(ibsng_server: FakeIBSngServer) -> Generator[None, None, None]:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Downgrade to base to ensure a clean schema. A completely fresh
    # database exits 0 here (alembic just sees current == base), so the
    # only failure we tolerate is "the tables aren't there to drop".
    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if downgrade.returncode != 0:
        combined = f"{downgrade.stdout}\n{downgrade.stderr}".lower()
        if not any(marker in combined for marker in _BENIGN_DOWNGRADE_MARKERS):
            raise RuntimeError(
                f"alembic downgrade base failed:\n{downgrade.stdout}\n{downgrade.stderr}"
            )

    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if upgrade.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed:\n{upgrade.stdout}\n{upgrade.stderr}")
    yield


@pytest_asyncio.fixture(scope="session")
async def seeded_catalog(_migrate_test_database: None) -> dict[str, list[dict[str, Any]]]:
    """Reads back - once, right after the migrations have run - whatever
    rows revision 0002 actually seeded into `groups` and `plans`, and
    caches them as plain Python data.

    This is deliberately a read-back rather than an import of a shared
    constant: the migration is a frozen historical record and nothing in
    the app or the test suite should be able to redefine what it inserted.
    The cache exists because the migration seeds once per session while
    _clean_database TRUNCATEs before every test."""
    from sqlalchemy import text

    from app.db.session import engine

    # "id" is prepended to every SELECT but deliberately kept OUT of the
    # *_SEED_COLUMNS tuples, which are the model-derived "everything the
    # migration actually set" lists. _clean_database re-adds "id" itself
    # when it rebuilds the INSERT, so the ids cached here are the ids the
    # rows carry after every TRUNCATE/re-seed cycle too - see the
    # id-pinning note there. Tests that need a real Plan/Group id - to
    # satisfy a foreign key or pass one to a service function - can read
    # it off the cached dict instead of a live query.
    async with engine.connect() as conn:
        group_rows = (
            await conn.execute(text(f"SELECT id, {', '.join(_GROUP_SEED_COLUMNS)} FROM groups ORDER BY id"))
        ).mappings().all()
        plan_rows = (
            await conn.execute(text(f"SELECT id, {', '.join(_PLAN_SEED_COLUMNS)} FROM plans ORDER BY id"))
        ).mappings().all()
        platform_rows = (
            await conn.execute(text(f"SELECT id, {', '.join(_PLATFORM_SEED_COLUMNS)} FROM tutorial_platforms ORDER BY id"))
        ).mappings().all()
        protocol_rows = (
            await conn.execute(text(f"SELECT id, {', '.join(_PROTOCOL_SEED_COLUMNS)} FROM tutorial_protocols ORDER BY id"))
        ).mappings().all()

    cached = {
        "groups": [dict(row) for row in group_rows],
        "plans": [dict(row) for row in plan_rows],
        "platforms": [dict(row) for row in platform_rows],
        "protocols": [dict(row) for row in protocol_rows],
    }
    if not cached["groups"] or not cached["plans"] or not cached["platforms"] or not cached["protocols"]:
        raise RuntimeError(
            "The catalog migration seeded no groups/plans/platforms/protocols - the per-test re-seed would "
            "silently leave every catalog test running against an empty catalog."
        )
    return cached


def _insert_statement(table: str, columns: tuple[str, ...]) -> str:
    placeholders = ", ".join(f":{column}" for column in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


def _resync_sequence_statement(table: str) -> str:
    """Pushes `table`'s id sequence past the highest id just re-seeded.

    The re-seed INSERTs supply their own ids (see _clean_database), which
    leaves the sequence sitting wherever RESTART IDENTITY put it (1). A
    test that then inserts its OWN row into one of these tables and lets
    the DB assign the id - e.g. the sync-groups test, whose sync_groups()
    does session.add(Group(name=...)) - would otherwise collide with a
    pinned seed id and fail on the primary key."""
    return (
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
        f"(SELECT COALESCE(MAX(id), 1) FROM {table}))"
    )


@pytest_asyncio.fixture(autouse=True)
async def _clean_database(seeded_catalog: dict[str, list[dict[str, Any]]]) -> AsyncGenerator[None, None]:
    from sqlalchemy import text

    from app.db.base import Base
    from app.db.session import engine

    table_names = [t.name for t in Base.metadata.sorted_tables]
    async with engine.begin() as conn:
        if table_names:
            await conn.execute(text(f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"))

        # Restore the catalog the migration seeded (TRUNCATE wiped it).
        #
        # Every re-seed INSERT pins "id" explicitly instead of letting the
        # restarted identity sequence reassign one. Without that pinning
        # the re-inserted rows get fresh ids starting at 1, while
        # seeded_catalog still caches the ids the MIGRATIONS assigned
        # (revision 0004 deletes 0002's four placeholder plans and inserts
        # the seven real ones, so those land on ids 5-11, not 1-7) - so
        # every `seeded_catalog["plans"][i]["id"]` silently pointed at the
        # wrong row, or at no row at all, from the very first test onward.
        # Pinning makes the cached ids true for the whole session.
        for table, columns, key in (
            ("groups", _GROUP_SEED_COLUMNS, "groups"),
            ("plans", _PLAN_SEED_COLUMNS, "plans"),
            ("tutorial_platforms", _PLATFORM_SEED_COLUMNS, "platforms"),
            ("tutorial_protocols", _PROTOCOL_SEED_COLUMNS, "protocols"),
        ):
            insert_stmt = text(_insert_statement(table, ("id",) + columns))
            for row in seeded_catalog[key]:
                await conn.execute(insert_stmt, row)
            await conn.execute(text(_resync_sequence_statement(table)))

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


@pytest_asyncio.fixture(autouse=True)
async def _reset_dispatcher_fsm_storage(dispatcher: Any) -> AsyncGenerator[None, None]:
    """The `dispatcher` fixture is session-scoped (aiogram Routers refuse
    to attach to a second Dispatcher), so its MemoryStorage outlives
    every test. Distinct telegram_ids keep that mostly harmless, but a
    test that fails partway through an FSM flow - or a future flow with
    an exit path that never reaches state.clear() - would otherwise leave
    state behind for whatever runs next. MemoryStorage keeps everything
    in a plain `.storage` defaultdict keyed by StorageKey; emptying it
    resets both state and data for every key at once."""
    yield
    dispatcher.storage.storage.clear()


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
    """The real production Dispatcher - built by app.main.build_dispatcher,
    the exact same call main() makes, differing only in the storage
    backend. Never hand-duplicate the wiring here: doing so is how the
    global error handler shipped registered in main() but absent from
    every test.

    Session-scoped: aiogram Router objects are module-level singletons and
    refuse to attach to more than one Dispatcher. Safe to share across the
    whole session because tests use distinct telegram_ids where it matters
    AND because _reset_dispatcher_fsm_storage below empties its FSM
    storage between tests (admin-flow tests all reuse FAKE_ADMIN_ID, so
    that reset is load-bearing, not just belt-and-braces)."""
    from aiogram.fsm.storage.memory import MemoryStorage

    from app.main import build_dispatcher

    return build_dispatcher(MemoryStorage())
