# Homeland Bot — Bootstrap & Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Homeland's repo, infra, and core plumbing — config, DB/Redis, the ported `IBSngClient`, a flat 4-plan catalog, and a minimal English main menu that shows all 4 buttons with placeholder responses — as one working, testable bot, ready for the Buy/Renew/My Services/Admin plans to build on.

**Architecture:** Bootstrapped from AloBot (`/Users/peyman/telegram-bot`) — same stack and layered structure (aiogram router-per-domain, SQLAlchemy 2.0 + Alembic, Redis-backed FSM, `IBSngClient` as the sole IBSng entry point) — with AloBot's category/location/reseller/trial complexity stripped out in favor of a flat plan catalog, and a from-scratch test harness (fake IBSng XML-RPC server, fake Telegram session, isolated Postgres/Redis via `docker-compose.test.yml`) ported from AloBot's proven pattern.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 (async, asyncpg), Alembic, PostgreSQL 16, Redis 7, pydantic-settings, pytest + pytest-asyncio, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-14-homeland-bot-design.md`

## Global Constraints

- Python 3.12+, aiogram >=3.4,<4, SQLAlchemy >=2.0,<3 (from the spec's stack; matches AloBot's pinned floors).
- Async only — no blocking I/O in handlers or services (carried over from AloBot's CLAUDE.md convention; still applies).
- Type hints on every function signature.
- All user-facing AND admin-facing strings in English (spec §"Language").
- Every interactive flow/menu includes a "Back" (and "Back to Menu" where relevant) button by default (spec §3, §7).
- `app/config.py`'s `Settings` is the single source of truth for config — no hardcoded secrets, ever (spec §11; AloBot convention).
- `app/services/ibsng/client.py` is the ONLY place that calls the IBSng API — never call IBSng from handlers or other services directly (spec §2.1; AloBot convention, unchanged).
- IBSng operations (create/renew user) must be idempotent — check state before acting, safe to retry (AloBot convention, unchanged).
- New feature = new router + new service method, not a growing god-file (AloBot convention, unchanged).
- Don't add dependencies or abstractions beyond what the current feature needs.
- `get_user_data_usage` (real IBSng quota reading) is explicitly OUT of scope for this plan — `user_balance.getUserBalanceInfoByUserID` is confirmed dead on this server (spec §5, §14) and needs to be probed against the real server as part of the My Services plan, not guessed at here.

---

## File Structure

```
Homeland-bot/
├── app/
│   ├── __init__.py
│   ├── config.py                     # Settings (pydantic-settings)
│   ├── redis.py                      # get_redis()
│   ├── main.py                       # bot entrypoint, router/middleware wiring
│   ├── db/
│   │   ├── base.py                   # DeclarativeBase
│   │   ├── session.py                # async engine + async_session_maker
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── bot_user.py
│   │       ├── admin_user.py
│   │       ├── app_config.py
│   │       ├── group.py
│   │       ├── plan.py
│   │       └── vpn_user.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── admin_users.py            # has_level, list_admins
│   │   ├── bot_users.py              # record_seen, is_blocked, block_user
│   │   ├── app_config.py             # get_config, set_config
│   │   ├── catalog.py                # list_plans, get_plan, update_plan, format_price_usd
│   │   ├── groups.py                 # sync_groups, list_groups
│   │   └── ibsng/
│   │       ├── __init__.py
│   │       ├── client.py             # IBSngClient
│   │       └── exceptions.py
│   └── bot/
│       ├── __init__.py
│       ├── error_handlers.py
│       ├── keyboards/
│       │   ├── __init__.py
│       │   └── menus.py              # main_menu (back_to_menu_keyboard added by a later plan)
│       ├── middlewares/
│       │   ├── __init__.py
│       │   ├── user_tracking.py
│       │   ├── blocked_user.py
│       │   └── private_chat_only.py
│       └── handlers/
│           ├── __init__.py
│           ├── users.py              # /start, send_main_menu, placeholder callbacks
│           └── fallback.py
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_core_tables.py
│       ├── 0002_catalog.py
│       └── 0003_vpn_users.py
├── scripts/
│   ├── setup.sh
│   └── ibsng_probe.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── factories.py
│   ├── fakes/
│   │   ├── __init__.py
│   │   ├── fake_ibsng_server.py
│   │   └── fake_bot_session.py
│   ├── unit/
│   │   ├── __init__.py
│   │   └── test_config.py
│   └── functional/
│       ├── __init__.py
│       ├── test_smoke_infra.py
│       ├── test_admin_and_bot_users.py
│       ├── test_ibsng_client.py
│       ├── test_catalog.py
│       ├── test_groups.py
│       ├── test_vpn_user_model.py
│       └── test_start_and_menu.py
├── alembic.ini
├── docker-compose.yml
├── docker-compose.test.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── Makefile
├── .env.example
├── .gitignore
├── CLAUDE.md
└── README.md
```

Each model/service file has one responsibility, mirroring AloBot's split. `tests/unit/` is new relative to AloBot (which only had `tests/functional/`) — it holds the one test in this plan that needs no DB/Docker at all (`Settings` validation), so that cycle stays fast; every DB-touching test stays under `tests/functional/`, unchanged from AloBot's convention.

---

## Task 1: Repo scaffold, config, and Docker skeleton

**Files:**
- Create: `Dockerfile`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `Makefile`, `.gitignore`, `.env.example`, `scripts/setup.sh`
- Create: `docker-compose.yml`, `docker-compose.test.yml`
- Create: `app/__init__.py`, `app/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `app.config.get_settings() -> Settings` (cached), `Settings.admin_id_list -> list[int]`, `Settings.database_url -> str`, `Settings.redis_url -> str`.

- [ ] **Step 1: Write the failing test for `Settings`**

```python
# tests/unit/test_config.py
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError


def _clear_settings_cache() -> None:
    from app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("BOT_TOKEN", "ADMIN_IDS", "IBSNG_", "POSTGRES_", "REDIS_", "STRIPE_", "CRYPTO_GATEWAY_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.setenv("IBSNG_BASE_URL", "http://ibsng.example:1235")
    monkeypatch.setenv("IBSNG_USERNAME", "admin")
    monkeypatch.setenv("IBSNG_PASSWORD", "secret")
    monkeypatch.setenv("IBSNG_ISP_NAME", "homeland")
    _clear_settings_cache()
    yield
    _clear_settings_cache()


def test_settings_load_with_required_fields():
    from app.config import get_settings

    settings = get_settings()
    assert settings.bot_token == "123:TEST"
    assert settings.ibsng_isp_name == "homeland"
    assert settings.postgres_db == "homeland"
    assert settings.webhook_port == 8090


def test_settings_admin_id_list_parses_csv(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ADMIN_IDS", "111,222, 333")
    _clear_settings_cache()
    assert get_settings().admin_id_list == [111, 222, 333]


def test_settings_rejects_blank_isp_name(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("IBSNG_ISP_NAME", "   ")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_database_and_redis_urls():
    from app.config import get_settings

    settings = get_settings()
    assert settings.database_url == (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    assert settings.redis_url == f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/unit/test_config.py -v` (requirements files don't exist yet either — write Step 3 first if your tool insists on running commands in order; the point of this step is confirming `ModuleNotFoundError: No module named 'app'`).

Expected: FAIL — `app` module not found.

- [ ] **Step 3: Create `requirements.txt` and `requirements-dev.txt`**

```
# requirements.txt
aiogram>=3.4,<4
SQLAlchemy>=2.0,<3
alembic>=1.13
asyncpg>=0.29
psycopg2-binary>=2.9
redis>=5.0
pydantic>=2.6
pydantic-settings>=2.2
httpx>=0.27
aiohttp>=3.9
```

```
# requirements-dev.txt
-r requirements.txt

pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 4: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = session
asyncio_default_test_loop_scope = session
testpaths = tests
```

- [ ] **Step 5: Write `app/config.py`**

```python
# app/config.py
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    admin_ids: str = ""

    # IBSng (XML-RPC) - same instance AloBot uses, Homeland's own ISP
    # name/credentials/groups. See app/services/ibsng/client.py.
    ibsng_base_url: str
    ibsng_username: str
    ibsng_password: str
    ibsng_isp_name: str
    ibsng_auth_remoteaddr: str = "127.0.0.1"
    ibsng_owner_name: str = ""

    @field_validator("ibsng_isp_name")
    @classmethod
    def _isp_name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "IBSNG_ISP_NAME must be set to the ISP name configured in your IBSng "
                "install (check the IBSng admin panel) - user.addNewUsers requires it."
            )
        return value

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "homeland"
    postgres_user: str = "homeland"
    postgres_password: str = "changeme"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    environment: str = "production"
    log_level: str = "INFO"

    support_username: str = ""

    webhook_port: int = 8090

    # Stripe - config placeholders only, no live keys yet (see spec §6).
    # create_invoice raises PaymentProviderNotConfiguredError while blank.
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""

    # Crypto gateway - config placeholders only, no live keys yet.
    crypto_gateway_api_key: str = ""
    crypto_gateway_ipn_secret: str = ""
    crypto_gateway_ipn_callback_url: str = ""

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Create `app/__init__.py` (empty)**

- [ ] **Step 7: Run the test to verify it passes**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Write the Docker/infra files**

```dockerfile
# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "app.main"]
```

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16-alpine
    command: ["postgres", "-c", "max_connections=100"]
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:
```

Note: the `bot` service is added to this file in Task 9, once `app/main.py` exists.

```yaml
# docker-compose.test.yml
# Fully isolated test stack - own Postgres/Redis, own project name, no
# shared volumes/network with docker-compose.yml. The fake IBSng
# XML-RPC server and fake Telegram session both run in-process inside
# the test-runner container (see tests/fakes/), not as separate
# services - nothing here ever reaches real IBSng or real Telegram.
#
# Run with an explicit project name so this never collides with the
# production stack on the same host:
#   docker compose -f docker-compose.test.yml -p homeland_bot_test run --rm test-runner <command>

services:
  db_test:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: homeland_test
      POSTGRES_USER: homeland_test
      POSTGRES_PASSWORD: homeland_test
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U homeland_test -d homeland_test"]
      interval: 3s
      timeout: 3s
      retries: 10

  redis_test:
    image: redis:7-alpine
    tmpfs:
      - /data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 10

  test-runner:
    build: .
    depends_on:
      db_test:
        condition: service_healthy
      redis_test:
        condition: service_healthy
    environment:
      BOT_TOKEN: "123456:TEST-TOKEN-NEVER-SENT-TO-REAL-TELEGRAM"
      ADMIN_IDS: "111111111"
      IBSNG_BASE_URL: "http://127.0.0.1:8765"
      IBSNG_USERNAME: "test"
      IBSNG_PASSWORD: "test"
      IBSNG_ISP_NAME: "test-isp"
      IBSNG_AUTH_REMOTEADDR: "127.0.0.1"
      POSTGRES_HOST: db_test
      POSTGRES_PORT: "5432"
      POSTGRES_DB: homeland_test
      POSTGRES_USER: homeland_test
      POSTGRES_PASSWORD: homeland_test
      REDIS_HOST: redis_test
      REDIS_PORT: "6379"
      REDIS_DB: "0"
      ENVIRONMENT: "test"
      LOG_LEVEL: "WARNING"
    command: ["sleep", "infinity"]
```

```makefile
# Makefile
.PHONY: setup build up down restart logs migrate bot test test-down

setup:
	bash scripts/setup.sh

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec bot alembic upgrade head

bot:
	docker compose exec bot python -m app.main

_TEST_COMPOSE = docker compose -f docker-compose.test.yml -p homeland_bot_test

test:
	$(_TEST_COMPOSE) up -d --build
	$(_TEST_COMPOSE) exec -T test-runner pip install -q -r requirements-dev.txt
	$(_TEST_COMPOSE) exec -T test-runner python -m pytest tests/ -v

test-down:
	$(_TEST_COMPOSE) down -v
```

```
# .gitignore
__pycache__/
*.pyc
.env
.venv/
venv/
*.egg-info/
.pytest_cache/
```

```bash
# scripts/setup.sh
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENV_FILE=".env"

ask() {
  local prompt_text=$1 default_value=${2:-} input
  if [[ -n "$default_value" ]]; then
    printf '%s [%s]: ' "$prompt_text" "$default_value" >&2
  else
    printf '%s: ' "$prompt_text" >&2
  fi
  read -r input
  echo "${input:-$default_value}"
}

ask_secret() {
  local prompt_text=$1 input
  printf '%s: ' "$prompt_text" >&2
  read -rs input
  echo >&2
  echo "$input"
}

echo "=== Homeland Bot setup ===" >&2
echo >&2

if [[ -f "$ENV_FILE" ]]; then
  read -rp ".env already exists. Overwrite? [y/N]: " overwrite
  if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
    echo "Aborted. Existing .env left untouched." >&2
    exit 0
  fi
fi

echo "--- Telegram ---" >&2
BOT_TOKEN=$(ask_secret "Telegram Bot Token")
ADMIN_IDS=$(ask "Admin Telegram User ID(s), comma-separated")

echo "--- IBSng (XML-RPC, same server as AloBot, Homeland's own ISP/groups) ---" >&2
IBSNG_BASE_URL=$(ask "IBSng XML-RPC base URL, e.g. http://YOUR_HOST:1235")
IBSNG_USERNAME=$(ask "IBSng admin username" "admin")
IBSNG_PASSWORD=$(ask_secret "IBSng admin password")
IBSNG_ISP_NAME=$(ask "IBSng ISP name")
IBSNG_AUTH_REMOTEADDR=$(ask "IBSng auth_remoteaddr (must be in TRUSTED_CLIENTS if not localhost)" "127.0.0.1")

echo "--- Database (PostgreSQL) ---" >&2
POSTGRES_HOST=$(ask "PostgreSQL host" "db")
POSTGRES_PORT=$(ask "PostgreSQL port" "5432")
POSTGRES_DB=$(ask "PostgreSQL database name" "homeland")
POSTGRES_USER=$(ask "PostgreSQL user" "homeland")
POSTGRES_PASSWORD=$(ask_secret "PostgreSQL password")

echo "--- Redis ---" >&2
REDIS_HOST=$(ask "Redis host" "redis")
REDIS_PORT=$(ask "Redis port" "6379")
REDIS_DB=$(ask "Redis DB index" "0")

echo "--- App ---" >&2
ENVIRONMENT=$(ask "Environment (production/development)" "production")
LOG_LEVEL=$(ask "Log level" "INFO")
WEBHOOK_PORT=$(ask "Local port for the payment webhook server" "8090")

cat > "$ENV_FILE" <<EOF
# Telegram
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS

# IBSng
IBSNG_BASE_URL=$IBSNG_BASE_URL
IBSNG_USERNAME=$IBSNG_USERNAME
IBSNG_PASSWORD=$IBSNG_PASSWORD
IBSNG_ISP_NAME=$IBSNG_ISP_NAME
IBSNG_AUTH_REMOTEADDR=$IBSNG_AUTH_REMOTEADDR

# Database
POSTGRES_HOST=$POSTGRES_HOST
POSTGRES_PORT=$POSTGRES_PORT
POSTGRES_DB=$POSTGRES_DB
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$POSTGRES_PASSWORD

# Redis
REDIS_HOST=$REDIS_HOST
REDIS_PORT=$REDIS_PORT
REDIS_DB=$REDIS_DB

# App
ENVIRONMENT=$ENVIRONMENT
LOG_LEVEL=$LOG_LEVEL
WEBHOOK_PORT=$WEBHOOK_PORT

# Stripe - leave blank until keys are provisioned (see docs/superpowers/specs)
STRIPE_API_KEY=
STRIPE_WEBHOOK_SECRET=

# Crypto gateway - leave blank until keys are provisioned
CRYPTO_GATEWAY_API_KEY=
CRYPTO_GATEWAY_IPN_SECRET=
CRYPTO_GATEWAY_IPN_CALLBACK_URL=
EOF

chmod 600 "$ENV_FILE"

echo >&2
echo ".env file generated." >&2
echo "Next steps:" >&2
echo "  make up       # docker compose up -d --build" >&2
echo "  make migrate  # apply database migrations" >&2
```

```
# .env.example
# Telegram
BOT_TOKEN=
ADMIN_IDS=123456789,987654321

# IBSng (XML-RPC) - same server AloBot uses, Homeland's own ISP name/
# credentials/groups. No path suffix, default port 1235.
IBSNG_BASE_URL=http://YOUR_IBSNG_HOST:1235
IBSNG_USERNAME=
IBSNG_PASSWORD=
IBSNG_ISP_NAME=
IBSNG_AUTH_REMOTEADDR=127.0.0.1

# Database
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=homeland
POSTGRES_USER=homeland
POSTGRES_PASSWORD=changeme

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# App
ENVIRONMENT=production
LOG_LEVEL=INFO
WEBHOOK_PORT=8090

# Stripe - placeholders, no live keys yet (see docs/superpowers/specs/2026-09-14-homeland-bot-design.md §6)
STRIPE_API_KEY=
STRIPE_WEBHOOK_SECRET=

# Crypto gateway - placeholders, no live keys yet
CRYPTO_GATEWAY_API_KEY=
CRYPTO_GATEWAY_IPN_SECRET=
CRYPTO_GATEWAY_IPN_CALLBACK_URL=
```

- [ ] **Step 9: Validate the compose files and bring up test infra**

Run: `docker compose -f docker-compose.test.yml -p homeland_bot_test config -q && docker compose -f docker-compose.test.yml -p homeland_bot_test up -d db_test redis_test`
Expected: no errors; `docker compose -f docker-compose.test.yml -p homeland_bot_test ps` shows both containers healthy.

- [ ] **Step 10: Commit**

```bash
git add Dockerfile requirements.txt requirements-dev.txt pytest.ini Makefile .gitignore .env.example \
        scripts/setup.sh docker-compose.yml docker-compose.test.yml app/__init__.py app/config.py \
        tests/unit/__init__.py tests/unit/test_config.py
git commit -m "feat: repo scaffold, Settings config, Docker test infra"
```

(Create `tests/unit/__init__.py` as an empty file first if it doesn't exist — `git add` needs it to exist to be tracked.)

---

## Task 2: Database foundation and first migration

**Files:**
- Create: `app/db/base.py`, `app/db/session.py`, `app/redis.py`
- Create: `app/db/models/__init__.py`, `app/db/models/bot_user.py`, `app/db/models/admin_user.py`, `app/db/models/app_config.py`
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_core_tables.py`

**Interfaces:**
- Consumes: `app.config.get_settings()` (Task 1).
- Produces: `app.db.base.Base` (DeclarativeBase), `app.db.session.async_session_maker`, `app.db.session.engine`, `app.redis.get_redis() -> redis.asyncio.Redis`, models `BotUser`, `AdminUser`, `AppConfig`.

- [ ] **Step 1: Write `app/db/base.py`, `app/db/session.py`, `app/redis.py`**

```python
# app/db/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
# app/db/session.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url, pool_pre_ping=True, pool_size=20, max_overflow=20, pool_timeout=5
)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

```python
# app/redis.py
import redis.asyncio as redis

from app.config import get_settings


def get_redis() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)
```

- [ ] **Step 2: Write the core models**

```python
# app/db/models/bot_user.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotUser(Base):
    """Every distinct telegram_id that has ever interacted with the bot,
    recorded by UserTrackingMiddleware on first sight - the recipient
    list for admin broadcasts."""

    __tablename__ = "bot_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
```

```python
# app/db/models/admin_user.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminUser(Base):
    """Admin-added admins with a permission level, on top of the
    always-full-access bootstrap admins from ADMIN_IDS (see
    app.services.admin_users). level is one of the ordered tiers in
    app.services.admin_users.LEVELS - "support" < "sales" < "full"."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    level: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# app/db/models/app_config.py
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppConfig(Base):
    """Admin-editable key/value settings that shouldn't require a
    redeploy to change - e.g. support text, ToS/Privacy content."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(4096))
```

```python
# app/db/models/__init__.py
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser

__all__ = ["AdminUser", "AppConfig", "BotUser"]
```

(`Group`, `Plan`, `VPNUser` are added to this `__init__.py` in Tasks 6 and 7.)

- [ ] **Step 3: Write Alembic scaffolding**

```ini
# alembic.ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

sqlalchemy.url = driver://user:pass@localhost/dbname

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.base import Base
from app.db.models import *  # noqa: F401,F403

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

```mako
# alembic/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

```python
# alembic/versions/0001_core_tables.py
"""core tables: bot_users, admin_users, app_config

Revision ID: 0001
Revises:
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(32), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_bot_users_telegram_id", "bot_users", ["telegram_id"], unique=True)

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_users_telegram_id", "admin_users", ["telegram_id"], unique=True)

    op.create_table(
        "app_config",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(4096), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_config")
    op.drop_index("ix_admin_users_telegram_id", table_name="admin_users")
    op.drop_table("admin_users")
    op.drop_index("ix_bot_users_telegram_id", table_name="bot_users")
    op.drop_table("bot_users")
```

- [ ] **Step 4: Verify the migration applies cleanly against the test DB**

Run:
```bash
docker compose -f docker-compose.test.yml -p homeland_bot_test up -d db_test
docker compose -f docker-compose.test.yml -p homeland_bot_test run --rm \
  -e POSTGRES_HOST=db_test -e POSTGRES_PORT=5432 -e POSTGRES_DB=homeland_test \
  -e POSTGRES_USER=homeland_test -e POSTGRES_PASSWORD=homeland_test \
  -e BOT_TOKEN=123:TEST -e IBSNG_BASE_URL=http://x:1235 -e IBSNG_USERNAME=x \
  -e IBSNG_PASSWORD=x -e IBSNG_ISP_NAME=x \
  test-runner alembic upgrade head
docker compose -f docker-compose.test.yml -p homeland_bot_test exec db_test \
  psql -U homeland_test -d homeland_test -c '\dt'
```
Expected: `alembic upgrade head` exits 0; `\dt` lists `bot_users`, `admin_users`, `app_config`, and `alembic_version`.

- [ ] **Step 5: Commit**

```bash
git add app/db app/redis.py alembic.ini alembic/
git commit -m "feat: DB/Redis foundation and core tables migration"
```

---

## Task 3: Test harness (fake IBSng server, fake bot session, conftest, factories)

**Files:**
- Create: `tests/fakes/__init__.py`, `tests/fakes/fake_ibsng_server.py`, `tests/fakes/fake_bot_session.py`
- Create: `tests/factories.py`, `tests/conftest.py`
- Test: `tests/functional/test_smoke_infra.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, `app.db.session.engine`/`async_session_maker`, `app.redis.get_redis`, `app.db.models.BotUser`.
- Produces: pytest fixtures `ibsng_server`, `fake_session`, `bot`, `dispatcher` (session-scoped, empty router set until Task 8 extends it); `tests.factories.make_message_update`, `make_callback_update`, `seed_bot_user`, `FAKE_ADMIN_ID`.

- [ ] **Step 1: Write the fake IBSng XML-RPC server**

```python
# tests/fakes/fake_ibsng_server.py
"""In-process fake IBSng XML-RPC server for tests. Replicates the real
server's confirmed quirks (documented in app/services/ibsng/client.py's
module docstring) closely enough that IBSngClient's code paths exercise
realistically, without ever touching the real IBSng box.

Runs as a background thread inside the pytest process - started once
per test session by the ibsng_server fixture in conftest.py, reset
between tests via .reset().
"""

from __future__ import annotations

import threading
import time
import xmlrpc.client
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler


class _QuietRequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/", "/RPC2")

    def log_message(self, format, *args):  # noqa: A002 - matches base signature
        pass


class FakeIBSngServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._server: SimpleXMLRPCServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._users: dict[int, dict] = {}
        self._next_id = 1
        self._groups = ["HL-2W", "HL-1M", "HL-2M", "HL-3M"]

    def reset(self) -> None:
        with self._lock:
            self._users = {}
            self._next_id = 1

    def set_user_attr(self, username: str, key: str, value) -> None:
        """Test-only backdoor for seeding attrs no real API call can set
        directly (e.g. nearest_exp_date)."""
        with self._lock:
            found = self._find_by_username(username)
            if found is None:
                raise KeyError(f"no fake IBSng user named {username!r}")
            _, user = found
            user["attrs"][key] = value

    def start(self) -> None:
        self._server = SimpleXMLRPCServer(
            (self.host, self.port), requestHandler=_QuietRequestHandler, allow_none=True, logRequests=False
        )
        for prefix, methods in (
            ("group", {"listGroups": self._group_listGroups}),
            (
                "user",
                {
                    "getUserInfo": self._user_getUserInfo,
                    "addNewUsers": self._user_addNewUsers,
                    "updateUserAttrs": self._user_updateUserAttrs,
                    "delUser": self._user_delUser,
                },
            ),
            ("user_balance", {"getUserBalanceInfoByUserID": self._user_balance_not_found}),
        ):
            for name, fn in methods.items():
                self._server.register_function(fn, f"{prefix}.{name}")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.05)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _find_by_username(self, username: str) -> tuple[int, dict] | None:
        for uid, u in self._users.items():
            if u["attrs"].get("normal_username") == username:
                return uid, u
        return None

    def _group_listGroups(self, payload: dict) -> list[str]:
        return list(self._groups)

    def _user_getUserInfo(self, payload: dict):
        with self._lock:
            if "user_id" in payload:
                uid = int(payload["user_id"])
                user = self._users.get(uid)
            else:
                found = self._find_by_username(payload.get("normal_username", ""))
                uid, user = found if found else (None, None)
            if user is None:
                raise xmlrpc.client.Fault(1, "NORMAL_USERNAME_DOESNT_EXISTS|User does not exist")
            return {str(uid): {"basic_info": user["basic_info"], "attrs": user["attrs"], "user_repr": uid}}

    def _user_addNewUsers(self, payload: dict) -> list[int]:
        with self._lock:
            uid = self._next_id
            self._next_id += 1
            self._users[uid] = {
                "basic_info": {
                    "user_id": uid,
                    "group_name": payload["group_name"],
                    "owner_name": payload.get("owner_name"),
                    "credit": payload.get("credit", 0),
                },
                "attrs": {"user_id": uid},
            }
            return [uid]

    def _user_updateUserAttrs(self, payload: dict):
        with self._lock:
            uid = int(payload["user_id"])
            user = self._users.get(uid)
            if user is None:
                raise xmlrpc.client.Fault(1, "NORMAL_USERNAME_DOESNT_EXISTS|User does not exist")
            attrs = payload.get("attrs", {})
            if "normal_username" in attrs:
                required = (
                    "normal_username", "normal_generate_password", "normal_generate_password_len",
                    "normal_password", "normal_save", "normal_save_usernames",
                )
                missing = [k for k in required if k not in attrs]
                if missing:
                    raise xmlrpc.client.Fault(1, f"KeyError: {missing[0]}")
                user["attrs"]["normal_username"] = attrs["normal_username"]
                user["attrs"]["normal_password"] = attrs["normal_password"]
            if "group_name" in attrs:
                user["basic_info"]["group_name"] = attrs["group_name"]
            if "lock" in attrs:
                user["attrs"]["lock"] = attrs["lock"]
            for key in payload.get("to_del_attrs", []):
                user["attrs"].pop(key, None)
            return True

    def _user_delUser(self, payload: dict):
        with self._lock:
            uid = int(payload["user_id"])
            if uid not in self._users:
                raise xmlrpc.client.Fault(1, "NORMAL_USERNAME_DOESNT_EXISTS|User does not exist")
            del self._users[uid]
            return True

    def _user_balance_not_found(self, payload: dict):
        raise xmlrpc.client.Fault(1, "Handler --user_balance-- not found")
```

- [ ] **Step 2: Write the fake bot session**

```python
# tests/fakes/fake_bot_session.py
"""In-process fake aiogram BaseSession - never makes a real HTTP call to
Telegram. Records every outbound API call (for test assertions) and
returns plausible synthetic responses for every method this codebase
actually calls, with a loud failure for anything uncovered."""

from __future__ import annotations

import datetime as dt
import itertools
from typing import Any

from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, ChatMemberOwner, Message, User


class FakeBotSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._message_id_counter = itertools.count(1)

    def reset(self) -> None:
        self.calls = []

    async def close(self) -> None:
        return None

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        raise NotImplementedError("FakeBotSession.stream_content is not implemented - this app doesn't use it")
        yield b""  # pragma: no cover

    def _fake_message(self, chat_id: int, **extra: Any) -> Message:
        return Message(
            message_id=next(self._message_id_counter),
            date=dt.datetime.now(dt.timezone.utc),
            chat=Chat(id=chat_id, type="private"),
            **extra,
        )

    async def make_request(self, bot, method, timeout: int | None = None):
        api_name = method.__api_method__
        data = method.model_dump(exclude_none=True)
        self.calls.append((api_name, data))

        chat_id = data.get("chat_id", 0)

        if api_name in ("sendMessage", "sendPhoto", "sendDocument", "sendVideo"):
            return self._fake_message(chat_id, text=data.get("text") or data.get("caption") or "")
        if api_name in ("editMessageText", "editMessageCaption", "editMessageReplyMarkup"):
            return self._fake_message(chat_id, text=data.get("text") or data.get("caption") or "")
        if api_name == "deleteMessage":
            return True
        if api_name == "answerCallbackQuery":
            return True
        if api_name == "getChatMember":
            return ChatMemberOwner(status="creator", user=User(id=data.get("user_id", 0), is_bot=False, first_name="Fake"), is_anonymous=False)
        if api_name == "getChat":
            return Chat(id=chat_id, type="private")
        if api_name == "setMyCommands":
            return True
        if api_name == "deleteWebhook":
            return True
        if api_name == "getMe":
            return User(id=999999, is_bot=True, first_name="TestBot", username="test_bot")

        returning = method.__returning__
        if returning is bool:
            return True
        if returning is int:
            return 0
        raise NotImplementedError(
            f"FakeBotSession has no handler for API method {api_name!r} (returning {returning!r}) - "
            "add one in tests/fakes/fake_bot_session.py rather than letting this call hit real Telegram."
        )
```

- [ ] **Step 3: Write `tests/factories.py`**

```python
# tests/factories.py
"""Helpers for constructing real aiogram Update/Message/CallbackQuery
objects, and for seeding the minimal DB rows each functional test
needs."""

from __future__ import annotations

import datetime as dt
import itertools

from aiogram.types import CallbackQuery, Chat, Message, Update, User

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


async def seed_bot_user(session, telegram_id: int, *, username: str | None = None) -> None:
    from app.db.models.bot_user import BotUser

    session.add(BotUser(telegram_id=telegram_id, username=username))
    await session.commit()
```

- [ ] **Step 4: Write `tests/conftest.py`**

```python
# tests/conftest.py
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
def ibsng_server():
    server = FakeIBSngServer(port=8765)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_database(ibsng_server):
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
async def _clean_database():
    from app.db.base import Base
    from app.db.session import engine
    from sqlalchemy import text

    table_names = [t.name for t in Base.metadata.sorted_tables]
    async with engine.begin() as conn:
        if table_names:
            await conn.execute(text(f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis():
    from app.redis import get_redis

    client = get_redis()
    await client.flushdb()
    await client.aclose()
    yield


@pytest.fixture(autouse=True)
def _reset_ibsng(ibsng_server):
    ibsng_server.reset()
    yield


@pytest.fixture
def fake_session() -> FakeBotSession:
    return FakeBotSession()


@pytest.fixture
def bot(fake_session):
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    return Bot(
        token=os.environ["BOT_TOKEN"],
        session=fake_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest_asyncio.fixture(scope="session")
async def dispatcher():
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
```

- [ ] **Step 5: Write the smoke test**

```python
# tests/functional/test_smoke_infra.py
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import seed_bot_user


@pytest.mark.asyncio
async def test_database_is_reachable_and_seedable():
    from app.db.models.bot_user import BotUser

    async with async_session_maker() as session:
        await seed_bot_user(session, 555, username="alice")

    async with async_session_maker() as session:
        row = (await session.execute(select(BotUser).where(BotUser.telegram_id == 555))).scalar_one()
        assert row.username == "alice"


@pytest.mark.asyncio
async def test_database_truncates_between_tests():
    """Depends on running after the seeding test above in file order -
    proves _clean_database actually truncates, not just that seeding
    works."""
    from app.db.models.bot_user import BotUser

    async with async_session_maker() as session:
        rows = (await session.execute(select(BotUser))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_redis_is_reachable():
    from app.redis import get_redis

    client = get_redis()
    await client.set("smoke", "ok")
    assert await client.get("smoke") == "ok"
    await client.aclose()


def test_fake_ibsng_server_responds(ibsng_server):
    import xmlrpc.client

    proxy = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{ibsng_server.port}")
    groups = proxy.group.listGroups({})
    assert groups == ["HL-2W", "HL-1M", "HL-2M", "HL-3M"]
```

- [ ] **Step 6: Run the tests to verify they fail first, then pass**

Run: `make test`
Expected: first run without the fixtures/fakes would fail with import errors; after Steps 1-5 above are all in place, `make test` should show 4 passing tests in `tests/functional/test_smoke_infra.py` plus the 4 from Task 1's `tests/unit/test_config.py`.

- [ ] **Step 7: Commit**

```bash
git add tests/
git commit -m "test: port fake IBSng server, fake bot session, conftest, and factories"
```

---

## Task 4: Admin/bot-user services and core middlewares

**Files:**
- Create: `app/services/__init__.py`, `app/services/admin_users.py`, `app/services/bot_users.py`, `app/services/app_config.py`
- Create: `app/bot/__init__.py`, `app/bot/middlewares/__init__.py`, `app/bot/middlewares/user_tracking.py`, `app/bot/middlewares/blocked_user.py`, `app/bot/middlewares/private_chat_only.py`
- Test: `tests/functional/test_admin_and_bot_users.py`

**Interfaces:**
- Consumes: `app.db.session.async_session_maker`, `app.db.models.{AdminUser, BotUser, AppConfig}` (Task 2), `app.config.get_settings` (Task 1).
- Produces: `admin_users.LEVELS = ("support", "sales", "full")`, `admin_users.has_level(session, telegram_id, min_level) -> bool`, `admin_users.list_admins(session) -> list[AdminUser]`; `bot_users.record_seen(session, telegram_id, username) -> None`, `bot_users.is_blocked(session, telegram_id) -> bool`, `bot_users.block_user(session, telegram_id, blocked=True) -> None`, `bot_users.list_bot_user_ids(session) -> list[int]`; `app_config.get_config(session, key) -> str | None`, `app_config.set_config(session, key, value) -> None`; middleware classes `UserTrackingMiddleware`, `BlockedUserMiddleware`, `PrivateChatOnlyMiddleware`.

- [ ] **Step 1: Write the failing test**

```python
# tests/functional/test_admin_and_bot_users.py
from __future__ import annotations

import pytest

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID


@pytest.mark.asyncio
async def test_env_admin_has_full_level_without_a_db_row():
    from app.services.admin_users import has_level

    async with async_session_maker() as session:
        assert await has_level(session, FAKE_ADMIN_ID, "full") is True


@pytest.mark.asyncio
async def test_unknown_user_has_no_level():
    from app.services.admin_users import has_level

    async with async_session_maker() as session:
        assert await has_level(session, 999, "support") is False


@pytest.mark.asyncio
async def test_db_admin_level_ordering():
    from app.db.models.admin_user import AdminUser
    from app.services.admin_users import has_level

    async with async_session_maker() as session:
        session.add(AdminUser(telegram_id=42, level="sales"))
        await session.commit()

    async with async_session_maker() as session:
        assert await has_level(session, 42, "support") is True
        assert await has_level(session, 42, "sales") is True
        assert await has_level(session, 42, "full") is False


@pytest.mark.asyncio
async def test_record_seen_creates_then_updates_username():
    from sqlalchemy import select

    from app.db.models.bot_user import BotUser
    from app.services.bot_users import record_seen

    async with async_session_maker() as session:
        await record_seen(session, 77, "first_name")
    async with async_session_maker() as session:
        await record_seen(session, 77, "changed_name")

    async with async_session_maker() as session:
        row = (await session.execute(select(BotUser).where(BotUser.telegram_id == 77))).scalar_one()
        assert row.username == "changed_name"


@pytest.mark.asyncio
async def test_block_and_unblock_user():
    from app.services.bot_users import block_user, is_blocked, record_seen

    async with async_session_maker() as session:
        await record_seen(session, 88, "target")

    async with async_session_maker() as session:
        assert await is_blocked(session, 88) is False
        await block_user(session, 88, blocked=True)

    async with async_session_maker() as session:
        assert await is_blocked(session, 88) is True
        await block_user(session, 88, blocked=False)

    async with async_session_maker() as session:
        assert await is_blocked(session, 88) is False


@pytest.mark.asyncio
async def test_app_config_get_set_roundtrip():
    from app.services.app_config import get_config, set_config

    async with async_session_maker() as session:
        assert await get_config(session, "support_username") is None
        await set_config(session, "support_username", "@homeland_support")

    async with async_session_maker() as session:
        assert await get_config(session, "support_username") == "@homeland_support"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.admin_users'`.

- [ ] **Step 3: Write the services**

```python
# app/services/__init__.py
```

```python
# app/services/admin_users.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.admin_user import AdminUser

LEVELS = ("support", "sales", "full")
LEVEL_LABELS = {"support": "Support", "sales": "Sales", "full": "Full"}


async def has_level(session: AsyncSession, telegram_id: int, min_level: str) -> bool:
    """Bootstrap admins from ADMIN_IDS always have full access, matching
    every level check. Otherwise looks up the DB-managed AdminUser row
    and compares tier order."""
    settings = get_settings()
    if telegram_id in settings.admin_id_list:
        return True
    row = (
        await session.execute(select(AdminUser).where(AdminUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is None:
        return False
    return LEVELS.index(row.level) >= LEVELS.index(min_level)


async def list_admins(session: AsyncSession) -> list[AdminUser]:
    return list((await session.execute(select(AdminUser))).scalars().all())
```

```python
# app/services/bot_users.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser


async def record_seen(session: AsyncSession, telegram_id: int, username: str | None) -> None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is None:
        session.add(BotUser(telegram_id=telegram_id, username=username))
    elif row.username != username:
        row.username = username
    await session.commit()


async def is_blocked(session: AsyncSession, telegram_id: int) -> bool:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    return row.is_blocked if row is not None else False


async def block_user(session: AsyncSession, telegram_id: int, blocked: bool = True) -> None:
    row = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if row is not None:
        row.is_blocked = blocked
        await session.commit()


async def list_bot_user_ids(session: AsyncSession) -> list[int]:
    return [row[0] for row in (await session.execute(select(BotUser.telegram_id))).all()]
```

```python
# app/services/app_config.py
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.app_config import AppConfig


async def get_config(session: AsyncSession, key: str) -> str | None:
    row = await session.get(AppConfig, key)
    return row.value if row is not None else None


async def set_config(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppConfig, key)
    if row is None:
        session.add(AppConfig(key=key, value=value))
    else:
        row.value = value
    await session.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test`
Expected: PASS — all 6 new tests plus everything from Tasks 1-3.

- [ ] **Step 5: Write the middlewares (no test file — exercised end to end in Task 8's dispatcher test; each one is a thin, pure pass-through/gate with no branching logic worth unit-testing in isolation)**

```python
# app/bot/__init__.py
```

```python
# app/bot/middlewares/__init__.py
```

```python
# app/bot/middlewares/private_chat_only.py
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

        chat = inner.message.chat if isinstance(inner, CallbackQuery) else inner.chat
        if chat is None or chat.type != ChatType.PRIVATE:
            return None

        return await handler(event, data)
```

```python
# app/bot/middlewares/user_tracking.py
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.db.session import async_session_maker
from app.services.bot_users import record_seen


class UserTrackingMiddleware(BaseMiddleware):
    """Records every distinct telegram_id that ever interacts with the
    bot, for the admin broadcast feature's recipient list."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        inner: Message | CallbackQuery | None = event.message or event.callback_query
        if inner is not None and inner.from_user is not None:
            async with async_session_maker() as session:
                await record_seen(session, inner.from_user.id, inner.from_user.username)

        return await handler(event, data)
```

```python
# app/bot/middlewares/blocked_user.py
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.bot_users import is_blocked

_BLOCKED_MESSAGE = "⛔️ You have been blocked from using this bot."


class BlockedUserMiddleware(BaseMiddleware):
    """Blocks every interaction (including /start) for a telegram_id an
    admin flagged via block_user. Admins are always exempt so a block
    can never lock out the panel itself."""

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
            if not await is_blocked(session, user_id):
                return await handler(event, data)

        if isinstance(inner, CallbackQuery):
            await inner.answer(_BLOCKED_MESSAGE, show_alert=True)
        else:
            await inner.answer(_BLOCKED_MESSAGE)
        return None
```

- [ ] **Step 6: Commit**

```bash
git add app/services/admin_users.py app/services/bot_users.py app/services/app_config.py app/services/__init__.py \
        app/bot/__init__.py app/bot/middlewares/ tests/functional/test_admin_and_bot_users.py
git commit -m "feat: admin/bot-user services and core middlewares"
```

---

## Task 5: IBSng client port

**Files:**
- Create: `app/services/ibsng/__init__.py`, `app/services/ibsng/exceptions.py`, `app/services/ibsng/client.py`
- Create: `scripts/ibsng_probe.py`
- Test: `tests/functional/test_ibsng_client.py`

**Interfaces:**
- Consumes: `app.config.get_settings` (Task 1), `tests.fakes.fake_ibsng_server.FakeIBSngServer` (Task 3, via the `ibsng_server` fixture).
- Produces: `IBSngClient` (async context manager) with `list_groups()`, `get_user_info()`, `get_user_expiry()`, `get_user_group()`, `get_user_password()`, `verify_user_credentials()`, `create_user(*, username, password, group_name, credit)`, `change_user_group()`, `change_user_password()`, `lock_user()`, `delete_user()`; exceptions `IBSngError`, `IBSngUserExistsError`, `IBSngUserNotFoundError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/functional/test_ibsng_client.py
from __future__ import annotations

import pytest

from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngUserExistsError, IBSngUserNotFoundError


@pytest.mark.asyncio
async def test_list_groups_returns_seeded_groups(ibsng_server):
    async with IBSngClient() as client:
        groups = await client.list_groups()
    assert groups == ["HL-2W", "HL-1M", "HL-2M", "HL-3M"]


@pytest.mark.asyncio
async def test_create_user_then_get_info(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="alice_vpn", password="pw123", group_name="HL-1M", credit=5120)
        info = await client.get_user_info(username="alice_vpn")

    assert info is not None


@pytest.mark.asyncio
async def test_create_user_twice_raises(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="bob_vpn", password="pw123", group_name="HL-1M", credit=5120)
        with pytest.raises(IBSngUserExistsError):
            await client.create_user(username="bob_vpn", password="pw123", group_name="HL-1M", credit=5120)


@pytest.mark.asyncio
async def test_get_user_expiry_reads_attrs(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="carol_vpn", password="pw123", group_name="HL-1M", credit=5120)
    ibsng_server.set_user_attr("carol_vpn", "nearest_exp_date", "2026-10-01 12:00")

    async with IBSngClient() as client:
        expiry = await client.get_user_expiry(username="carol_vpn")
    assert expiry == "2026-10-01 12:00"


@pytest.mark.asyncio
async def test_change_user_group(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="dave_vpn", password="pw123", group_name="HL-1M", credit=5120)
        await client.change_user_group(username="dave_vpn", group_name="HL-2M")
        group = await client.get_user_group(username="dave_vpn")
    assert group == "HL-2M"


@pytest.mark.asyncio
async def test_change_user_password_and_verify(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="erin_vpn", password="old-pw", group_name="HL-1M", credit=5120)
        await client.change_user_password(username="erin_vpn", new_password="new-pw")
        assert await client.verify_user_credentials(username="erin_vpn", password="new-pw") is True
        assert await client.verify_user_credentials(username="erin_vpn", password="old-pw") is False


@pytest.mark.asyncio
async def test_lock_and_delete_user(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="frank_vpn", password="pw123", group_name="HL-1M", credit=5120)
        await client.lock_user(username="frank_vpn", locked=True)
        await client.delete_user(username="frank_vpn")
        with pytest.raises(IBSngUserNotFoundError):
            await client.change_user_group(username="frank_vpn", group_name="HL-1M")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ibsng'`.

- [ ] **Step 3: Write `app/services/ibsng/exceptions.py`**

```python
# app/services/ibsng/exceptions.py
class IBSngError(Exception):
    """Base exception for all IBSng API errors."""


class IBSngUserExistsError(IBSngError):
    """Raised when attempting to create a user that already exists."""


class IBSngUserNotFoundError(IBSngError):
    """Raised when an operation targets a username that doesn't exist in IBSng."""
```

- [ ] **Step 4: Write `app/services/ibsng/client.py`**

```python
# app/services/ibsng/client.py
"""Single entry point for all IBSng API calls. Handlers and other
services must never call IBSng directly - always go through
IBSngClient.

Transport: XML-RPC over HTTP to IBSNG_BASE_URL (default port 1235 for
IBSng Free 1.24). Credentials are sent on EVERY call (auth_type=ADMIN,
auth_name, auth_pass, auth_remoteaddr merged into each method's
params) - this edition does not support reusable sessions.

Ported from AloBot's IBSngClient (/Users/peyman/telegram-bot), which
confirmed the following against a real IBSng Free 1.24 server - all of
it still applies here, same server:
- group.listGroups returns a plain list of group name strings.
- user.doesUserExists is not a valid handler method; existence checks
  call user.getUserInfo and treat a Fault as "does not exist".
- Create-user is user.addNewUsers(count, isp_name, owner_name,
  group_name, credit, credit_comment) -> [user_id], then
  user.updateUserAttrs to set normal_username/normal_password with a
  FLAT six-key attrs shape (not the nested normal_user_spec shape the
  commercial docs describe - that shape is silently ignored here).
  owner_name is REQUIRED, defaults to IBSNG_USERNAME.
- user.getUserInfo's stored password and nearest_exp_date live under
  "attrs", not "basic_info".
- Changing a user's group is user.updateUserAttrs with attrs=
  {"group_name": <new name>} - group_id is silently ignored.
- Locking a user is user.updateUserAttrs with attrs={"lock": bool}.
- user_balance.getUserBalanceInfoByUserID is CONFIRMED DEAD on this
  server ("Handler --user_balance-- not found", confirmed live twice
  in AloBot's history) - do not use it for anything, including the
  quota feature (deferred to the My Services plan, which must probe
  for a working alternative first - see docs/superpowers/specs/
  2026-09-14-homeland-bot-design.md §5, §14).

Deviation from AloBot: create_user takes an explicit `credit` param
instead of a hardcoded default - Homeland's credit must always equal
the specific plan's data cap (spec §5), so there is no sensible
project-wide default to hardcode.
"""

from __future__ import annotations

import asyncio
import secrets
import xmlrpc.client
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError, IBSngUserNotFoundError

_TIMEOUT = 15.0


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


class IBSngClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._auth_name = settings.ibsng_username
        self._auth_pass = settings.ibsng_password
        self._auth_remoteaddr = settings.ibsng_auth_remoteaddr
        self._isp_name = settings.ibsng_isp_name
        self._owner_name = settings.ibsng_owner_name or settings.ibsng_username

        transport_cls = (
            _TimeoutSafeTransport if urlparse(settings.ibsng_base_url).scheme == "https" else _TimeoutTransport
        )
        self._proxy = xmlrpc.client.ServerProxy(
            settings.ibsng_base_url,
            transport=transport_cls(_TIMEOUT),
            allow_none=True,
        )

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> "IBSngClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def list_groups(self) -> list[str]:
        raw = await self._call("group.listGroups")
        return [str(name) for name in (raw or [])]

    async def get_user_info(self, *, username: str | None = None, user_id: str | None = None) -> Any:
        params: dict[str, Any] = {}
        if username is not None:
            params["normal_username"] = username
        if user_id is not None:
            params["user_id"] = user_id
        return await self._call("user.getUserInfo", **params)

    async def verify_user_credentials(self, *, username: str, password: str) -> bool:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            return False
        _, inner = _split_user_info(info)
        if inner is None:
            return False

        stored: Any = None
        attrs = inner.get("attrs")
        if isinstance(attrs, dict):
            stored = attrs.get("normal_password")
        if stored is None:
            return False
        return secrets.compare_digest(str(stored), password)

    async def get_user_expiry(self, *, username: str) -> str | None:
        info = await self.get_user_info(username=username)
        _, inner = _split_user_info(info)
        if inner is None:
            return None
        attrs = inner.get("attrs")
        if isinstance(attrs, dict):
            exp = attrs.get("nearest_exp_date")
            if exp is not None:
                return str(exp)
        return None

    async def get_user_group(self, *, username: str) -> str | None:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            return None
        _, inner = _split_user_info(info)
        if inner is None:
            return None
        basic_info = inner.get("basic_info")
        if isinstance(basic_info, dict):
            group_name = basic_info.get("group_name")
            if group_name is not None:
                return str(group_name)
        return None

    async def get_user_password(self, *, username: str) -> str | None:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            return None
        _, inner = _split_user_info(info)
        if inner is None:
            return None
        attrs = inner.get("attrs")
        if isinstance(attrs, dict):
            stored = attrs.get("normal_password")
            if stored is not None:
                return str(stored)
        return None

    async def change_user_group(self, *, username: str, group_name: str) -> None:
        user_id = await self._require_user_id(username)
        await self._call(
            "user.updateUserAttrs", user_id=user_id, attrs={"group_name": group_name}, to_del_attrs=[]
        )

    async def change_user_password(self, *, username: str, new_password: str) -> None:
        user_id = await self._require_user_id(username)
        await self._call(
            "user.updateUserAttrs",
            user_id=user_id,
            attrs={
                "normal_username": username,
                "normal_generate_password": False,
                "normal_generate_password_len": 8,
                "normal_password": new_password,
                "normal_save": True,
                "normal_save_usernames": True,
            },
            to_del_attrs=[],
        )

    async def lock_user(self, *, username: str, locked: bool = True) -> None:
        user_id = await self._require_user_id(username)
        await self._call("user.updateUserAttrs", user_id=user_id, attrs={"lock": locked}, to_del_attrs=[])

    async def delete_user(self, *, username: str, comment: str = "Revoked via Telegram bot") -> None:
        user_id = await self._require_user_id(username)
        await self._call(
            "user.delUser",
            user_id=user_id,
            delete_comment=comment,
            del_connection_logs=True,
            del_audit_logs=True,
        )

    async def create_user(self, *, username: str, password: str, group_name: str, credit: int) -> str:
        """Idempotent: raises IBSngUserExistsError instead of creating a
        duplicate. credit must be the purchased plan's data_cap_mb (see
        module docstring) - always pass it explicitly, there is no
        default."""
        if await self._get_user_info_or_none(username=username) is not None:
            raise IBSngUserExistsError(f"IBSng user {username!r} already exists")

        user_ids = await self._call(
            "user.addNewUsers",
            count=1,
            isp_name=self._isp_name,
            owner_name=self._owner_name,
            group_name=group_name,
            credit=credit,
            credit_comment="Created via Homeland bot",
        )
        if not user_ids:
            raise IBSngError("IBSng addNewUsers returned no user_id")
        user_id = str(user_ids[0])

        await self._call(
            "user.updateUserAttrs",
            user_id=user_id,
            attrs={
                "normal_username": username,
                "normal_generate_password": False,
                "normal_generate_password_len": 8,
                "normal_password": password,
                "normal_save": True,
                "normal_save_usernames": True,
            },
            to_del_attrs=[],
        )
        return user_id

    async def _require_user_id(self, username: str) -> str:
        info = await self._get_user_info_or_none(username=username)
        if info is None:
            raise IBSngUserNotFoundError(f"IBSng user {username!r} not found")
        user_id, _ = _split_user_info(info)
        if user_id is None:
            raise IBSngError(f"Could not determine user_id for {username!r} from getUserInfo: {info!r}")
        return user_id

    async def _get_user_info_or_none(self, *, username: str) -> Any | None:
        payload = {
            "auth_type": "ADMIN",
            "auth_name": self._auth_name,
            "auth_pass": self._auth_pass,
            "auth_remoteaddr": self._auth_remoteaddr,
            "normal_username": username,
        }
        try:
            return await asyncio.to_thread(self._proxy.user.getUserInfo, payload)
        except xmlrpc.client.Fault:
            return None
        except (xmlrpc.client.ProtocolError, OSError) as exc:
            raise IBSngError(f"IBSng call 'user.getUserInfo' could not reach server: {exc}") from exc

    async def _call(self, method: str, **params: Any) -> Any:
        payload = {
            "auth_type": "ADMIN",
            "auth_name": self._auth_name,
            "auth_pass": self._auth_pass,
            "auth_remoteaddr": self._auth_remoteaddr,
            **params,
        }
        try:
            return await asyncio.to_thread(getattr(self._proxy, method), payload)
        except xmlrpc.client.Fault as exc:
            raise IBSngError(f"IBSng call {method!r} failed: {exc.faultString}") from exc
        except (xmlrpc.client.ProtocolError, OSError) as exc:
            raise IBSngError(f"IBSng call {method!r} could not reach server: {exc}") from exc


def _split_user_info(info: Any) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(info, dict):
        return None, None
    if "basic_info" in info:
        user_id = info.get("user_id")
        resolved = str(user_id) if user_id is not None and not isinstance(user_id, dict) else None
        return resolved, info
    if len(info) == 1:
        only_key, only_value = next(iter(info.items()))
        if isinstance(only_value, dict):
            return str(only_key), only_value
    return None, None
```

```python
# app/services/ibsng/__init__.py
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `make test`
Expected: PASS — all 7 new tests plus everything from Tasks 1-4.

- [ ] **Step 6: Port the diagnostic probe script (needed by the deferred My Services quota-probing task)**

```python
# scripts/ibsng_probe.py
#!/usr/bin/env python3
"""One-off diagnostic script for inspecting real IBSng data over
XML-RPC. Reads IBSNG_BASE_URL/IBSNG_USERNAME/etc. from the environment
(.env) - no hostname is ever hardcoded here.

Usage (run inside the bot container, or a venv with .env loaded):
  python scripts/ibsng_probe.py user <username>
  python scripts/ibsng_probe.py groups
  python scripts/ibsng_probe.py raw <handler.method> <json-payload>
"""

import asyncio
import json
import sys

from app.services.ibsng.client import IBSngClient


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    command = sys.argv[1]
    async with IBSngClient() as client:
        if command == "user" and len(sys.argv) == 3:
            result = await client.get_user_info(username=sys.argv[2])
        elif command == "groups":
            result = await client.list_groups()
        elif command == "raw" and len(sys.argv) == 4:
            # Free-form escape hatch for probing candidate handlers the
            # typed client doesn't wrap yet (e.g. quota/traffic data -
            # see docs/superpowers/specs/2026-09-14-homeland-bot-design.md §5).
            method_name, payload_json = sys.argv[2], sys.argv[3]
            result = await client._call(method_name, **json.loads(payload_json))  # noqa: SLF001
        else:
            print(__doc__)
            raise SystemExit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 7: Commit**

```bash
git add app/services/ibsng scripts/ibsng_probe.py tests/functional/test_ibsng_client.py
git commit -m "feat: port IBSngClient and exceptions from AloBot"
```

---

## Task 6: Catalog foundation (Group, Plan, seed data)

**Files:**
- Create: `app/db/models/group.py`, `app/db/models/plan.py`
- Modify: `app/db/models/__init__.py`
- Create: `alembic/versions/0002_catalog.py`
- Create: `app/services/groups.py`, `app/services/catalog.py`
- Test: `tests/functional/test_groups.py`, `tests/functional/test_catalog.py`

**Interfaces:**
- Consumes: `IBSngClient.list_groups()` (Task 5), `app.db.session.async_session_maker` (Task 2).
- Produces: models `Group(id, name, synced_at)`, `Plan(id, name, duration_days, data_cap_mb, price_usd, group_name, is_active, sort_order, created_at, updated_at)`; `groups.sync_groups(session, client) -> list[Group]`, `groups.list_groups(session) -> list[Group]`; `catalog.list_plans(session, *, active_only=True) -> list[Plan]`, `catalog.get_plan(session, plan_id) -> Plan | None`, `catalog.update_plan(session, plan_id, *, price_usd=None, group_name=None, is_active=None) -> Plan | None`, `catalog.format_price_usd(price: Decimal) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/functional/test_groups.py
from __future__ import annotations

import pytest

from app.db.session import async_session_maker
from app.services.ibsng.client import IBSngClient


@pytest.mark.asyncio
async def test_sync_groups_upserts_from_ibsng(ibsng_server):
    from app.services.groups import list_groups, sync_groups

    async with async_session_maker() as session, IBSngClient() as client:
        synced = await sync_groups(session, client)
    assert sorted(g.name for g in synced) == ["HL-1M", "HL-2M", "HL-2W", "HL-3M"]

    async with async_session_maker() as session:
        rows = await list_groups(session)
    assert sorted(g.name for g in rows) == ["HL-1M", "HL-2M", "HL-2W", "HL-3M"]


@pytest.mark.asyncio
async def test_sync_groups_is_idempotent(ibsng_server):
    from sqlalchemy import func, select

    from app.db.models.group import Group
    from app.services.groups import sync_groups

    async with async_session_maker() as session, IBSngClient() as client:
        await sync_groups(session, client)
    async with async_session_maker() as session, IBSngClient() as client:
        await sync_groups(session, client)

    async with async_session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(Group))).scalar_one()
    assert count == 4
```

```python
# tests/functional/test_catalog.py
from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_seed_migration_creates_four_plans():
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        plans = await list_plans(session)

    assert [p.name for p in plans] == ["2 Weeks", "1 Month", "2 Months", "3 Months"]
    assert [p.duration_days for p in plans] == [14, 30, 60, 90]
    assert [p.data_cap_mb for p in plans] == [2048, 5120, 10240, 102400]
    assert [p.price_usd for p in plans] == [Decimal("2.50"), Decimal("5.00"), Decimal("10.00"), Decimal("30.00")]
    assert [p.group_name for p in plans] == ["HL-2W", "HL-1M", "HL-2M", "HL-3M"]


@pytest.mark.asyncio
async def test_list_plans_active_only_excludes_inactive():
    from app.services.catalog import list_plans, update_plan

    async with async_session_maker() as session:
        plans = await list_plans(session)
        await update_plan(session, plans[0].id, is_active=False)

    async with async_session_maker() as session:
        active = await list_plans(session, active_only=True)
        everything = await list_plans(session, active_only=False)

    assert len(active) == 3
    assert len(everything) == 4


@pytest.mark.asyncio
async def test_update_plan_price_and_group():
    from app.services.catalog import get_plan, list_plans, update_plan

    async with async_session_maker() as session:
        plans = await list_plans(session)
        updated = await update_plan(session, plans[0].id, price_usd=Decimal("2.99"), group_name="HL-2W-v2")

    assert updated.price_usd == Decimal("2.99")
    assert updated.group_name == "HL-2W-v2"

    async with async_session_maker() as session:
        fetched = await get_plan(session, plans[0].id)
    assert fetched.price_usd == Decimal("2.99")


def test_format_price_usd():
    from app.services.catalog import format_price_usd

    assert format_price_usd(Decimal("2.50")) == "$2.50"
    assert format_price_usd(Decimal("30")) == "$30.00"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.groups'`.

- [ ] **Step 3: Write the models**

```python
# app/db/models/group.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Group(Base):
    """A locally cached copy of an IBSng group name, kept in sync via
    services.groups.sync_groups(). Exists so admin can pick a real,
    existing IBSng group when binding/rebinding a Plan, without calling
    IBSng on every keystroke."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    synced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

```python
# app/db/models/plan.py
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Plan(Base):
    """One of Homeland's 4 flat, fixed sale plans - no category/location/
    user-count matrix like AloBot's Service (spec §4). Admin can edit
    price/group_name/is_active but never creates a 5th plan through the
    bot; new plans are a schema/seed change, not an admin action."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    duration_days: Mapped[int] = mapped_column(Integer)
    data_cap_mb: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    group_name: Mapped[str] = mapped_column(String(64), ForeignKey("groups.name"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Update the models `__init__.py`**

```python
# app/db/models/__init__.py
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser
from app.db.models.group import Group
from app.db.models.plan import Plan

__all__ = ["AdminUser", "AppConfig", "BotUser", "Group", "Plan"]
```

- [ ] **Step 5: Write the migration (schema + seed data)**

```python
# alembic/versions/0002_catalog.py
"""catalog: groups, plans, seeded with Homeland's 4 fixed plans

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# These group names are placeholders until the real IBSng groups exist
# (spec §5, §14 - deployment prerequisite). Whoever creates the real
# groups in IBSng must either name them exactly this, or an admin must
# re-run sync_groups and repoint each Plan.group_name afterwards.
_PLANS = [
    ("2 Weeks", 14, 2048, "2.50", "HL-2W", 0),
    ("1 Month", 30, 5120, "5.00", "HL-1M", 1),
    ("2 Months", 60, 10240, "10.00", "HL-2M", 2),
    ("3 Months", 90, 102400, "30.00", "HL-3M", 3),
]


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_groups_name", "groups", ["name"], unique=True)

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("data_cap_mb", sa.Integer(), nullable=False),
        sa.Column("price_usd", sa.Numeric(6, 2), nullable=False),
        sa.Column("group_name", sa.String(64), sa.ForeignKey("groups.name"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_plans_group_name", "plans", ["group_name"])

    groups_table = sa.table("groups", sa.column("name", sa.String))
    plans_table = sa.table(
        "plans",
        sa.column("name", sa.String),
        sa.column("duration_days", sa.Integer),
        sa.column("data_cap_mb", sa.Integer),
        sa.column("price_usd", sa.Numeric),
        sa.column("group_name", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(groups_table, [{"name": group_name} for *_rest, group_name, _ in _PLANS])
    op.bulk_insert(
        plans_table,
        [
            {
                "name": name,
                "duration_days": duration_days,
                "data_cap_mb": data_cap_mb,
                "price_usd": price_usd,
                "group_name": group_name,
                "sort_order": sort_order,
            }
            for name, duration_days, data_cap_mb, price_usd, group_name, sort_order in _PLANS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_plans_group_name", table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_groups_name", table_name="groups")
    op.drop_table("groups")
```

- [ ] **Step 6: Write the services**

```python
# app/services/groups.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.group import Group
from app.services.ibsng.client import IBSngClient


async def sync_groups(session: AsyncSession, client: IBSngClient) -> list[Group]:
    """Upserts every IBSng group name into the local Group cache. Safe
    to call repeatedly - existing rows just get a fresh synced_at."""
    names = await client.list_groups()
    existing = {g.name: g for g in (await session.execute(select(Group))).scalars().all()}
    now = dt.datetime.now(dt.timezone.utc)

    result: list[Group] = []
    for name in names:
        if name in existing:
            existing[name].synced_at = now
            result.append(existing[name])
        else:
            group = Group(name=name)
            session.add(group)
            result.append(group)
    await session.commit()
    return result


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.execute(select(Group).order_by(Group.name))).scalars().all())
```

```python
# app/services/catalog.py
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.plan import Plan


async def list_plans(session: AsyncSession, *, active_only: bool = True) -> list[Plan]:
    query = select(Plan).order_by(Plan.sort_order, Plan.id)
    if active_only:
        query = query.where(Plan.is_active.is_(True))
    return list((await session.execute(query)).scalars().all())


async def get_plan(session: AsyncSession, plan_id: int) -> Plan | None:
    return await session.get(Plan, plan_id)


async def update_plan(
    session: AsyncSession,
    plan_id: int,
    *,
    price_usd: Decimal | None = None,
    group_name: str | None = None,
    is_active: bool | None = None,
) -> Plan | None:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        return None
    if price_usd is not None:
        plan.price_usd = price_usd
    if group_name is not None:
        plan.group_name = group_name
    if is_active is not None:
        plan.is_active = is_active
    await session.commit()
    await session.refresh(plan)
    return plan


def format_price_usd(price: Decimal) -> str:
    return f"${price:.2f}"
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test`
Expected: PASS — 2 tests in `test_groups.py`, 4 in `test_catalog.py`, plus everything from Tasks 1-5.

- [ ] **Step 8: Commit**

```bash
git add app/db/models/group.py app/db/models/plan.py app/db/models/__init__.py alembic/versions/0002_catalog.py \
        app/services/groups.py app/services/catalog.py tests/functional/test_groups.py tests/functional/test_catalog.py
git commit -m "feat: catalog foundation - Group/Plan models, seed migration, catalog/groups services"
```

---

## Task 7: VPNUser model

**Files:**
- Create: `app/db/models/vpn_user.py`
- Modify: `app/db/models/__init__.py`
- Create: `alembic/versions/0003_vpn_users.py`
- Test: `tests/functional/test_vpn_user_model.py`

**Interfaces:**
- Consumes: `Plan` (Task 6).
- Produces: model `VPNUser(id, telegram_id, ibsng_username, ibsng_group, plan_id, data_cap_mb, expires_at, expiry_reminder_sent_at, low_quota_reminder_sent_at, password_changed_at, created_at)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/functional/test_vpn_user_model.py
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_create_vpn_user_row_linked_to_a_plan():
    from app.db.models.vpn_user import VPNUser
    from app.services.catalog import list_plans

    async with async_session_maker() as session:
        plan = (await list_plans(session))[1]  # "1 Month", 5120 MB
        session.add(
            VPNUser(
                telegram_id=123,
                ibsng_username="gina_vpn",
                ibsng_group=plan.group_name,
                plan_id=plan.id,
                data_cap_mb=plan.data_cap_mb,
            )
        )
        await session.commit()

    async with async_session_maker() as session:
        row = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == "gina_vpn"))).scalar_one()
        assert row.telegram_id == 123
        assert row.data_cap_mb == 5120
        assert row.expires_at is None
        assert row.expiry_reminder_sent_at is None
        assert row.low_quota_reminder_sent_at is None


@pytest.mark.asyncio
async def test_ibsng_username_must_be_unique():
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=1, ibsng_username="dup_vpn", ibsng_group="HL-1M", data_cap_mb=5120))
        await session.commit()

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=2, ibsng_username="dup_vpn", ibsng_group="HL-1M", data_cap_mb=5120))
        with pytest.raises(IntegrityError):
            await session.commit()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.vpn_user'`.

- [ ] **Step 3: Write the model**

```python
# app/db/models/vpn_user.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VPNUser(Base):
    """An owned Homeland VPN account. data_cap_mb snapshots Plan.data_cap_mb
    at purchase/renewal time, so a later plan price/cap edit never
    retroactively changes an existing subscription (spec §5) - mirrors
    how the payment's charged amount is snapshotted rather than
    recomputed from the current plan price.

    expires_at/expiry_reminder_sent_at are read/written the same way
    AloBot's did (live from IBSng, not cached); low_quota_reminder_sent_at
    is new - see docs/superpowers/specs/2026-09-14-homeland-bot-design.md
    §8. Both reminder timestamps are cleared on renewal so the next
    cycle gets a fresh reminder."""

    __tablename__ = "vpn_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ibsng_username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ibsng_group: Mapped[str] = mapped_column(String(64))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    data_cap_mb: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    low_quota_reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Update the models `__init__.py`**

```python
# app/db/models/__init__.py
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser
from app.db.models.group import Group
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser

__all__ = ["AdminUser", "AppConfig", "BotUser", "Group", "Plan", "VPNUser"]
```

- [ ] **Step 5: Write the migration**

```python
# alembic/versions/0003_vpn_users.py
"""vpn_users table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vpn_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("ibsng_username", sa.String(64), nullable=False),
        sa.Column("ibsng_group", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("data_cap_mb", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("low_quota_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vpn_users_telegram_id", "vpn_users", ["telegram_id"])
    op.create_index("ix_vpn_users_ibsng_username", "vpn_users", ["ibsng_username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_vpn_users_ibsng_username", table_name="vpn_users")
    op.drop_index("ix_vpn_users_telegram_id", table_name="vpn_users")
    op.drop_table("vpn_users")
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `make test`
Expected: PASS — 2 tests in `test_vpn_user_model.py`, plus everything from Tasks 1-6.

- [ ] **Step 7: Commit**

```bash
git add app/db/models/vpn_user.py app/db/models/__init__.py alembic/versions/0003_vpn_users.py \
        tests/functional/test_vpn_user_model.py
git commit -m "feat: VPNUser model and migration"
```

---

## Task 8: Minimal bot — main menu with placeholder actions

**Files:**
- Create: `app/bot/keyboards/__init__.py`, `app/bot/keyboards/menus.py`
- Create: `app/bot/handlers/__init__.py`, `app/bot/handlers/users.py`, `app/bot/handlers/fallback.py`
- Create: `app/bot/error_handlers.py`
- Modify: `tests/conftest.py` (extend the `dispatcher` fixture)
- Test: `tests/functional/test_start_and_menu.py`

**Interfaces:**
- Consumes: `app.services.admin_users.has_level` (Task 4), `app.db.session.async_session_maker` (Task 2), `tests.factories.{make_message_update, make_callback_update, FAKE_ADMIN_ID}` (Task 3).
- Produces: `menus.main_menu(*, is_admin: bool) -> InlineKeyboardMarkup`; `users.router` (aiogram `Router`), `users.send_main_menu(target: Message) -> None`, `users.WELCOME_TEXT`, `users.PLACEHOLDER_TEXT`; `fallback.router`.

Note: `back_to_menu_keyboard()` (spec's standing "every flow has a Back
button" rule) is intentionally NOT added here — nothing in this plan has
a sub-screen to back out of yet (the 4 menu buttons are placeholders).
It belongs to `app/bot/keyboards/menus.py` too, added by whichever
follow-up plan (Buy/Renew/My Services/Tutorial & Support) first builds a
real sub-screen, so it ships with an actual consumer and test instead of
as untested dead code.

- [ ] **Step 1: Write the failing test**

```python
# tests/functional/test_start_and_menu.py
from __future__ import annotations

import pytest

from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update


@pytest.mark.asyncio
async def test_start_shows_english_main_menu(dispatcher, bot, fake_session):
    update = make_message_update(999, "/start")
    await dispatcher.feed_update(bot, update)

    sent = [call for call in fake_session.calls if call[0] == "sendMessage"]
    assert len(sent) == 1
    _, data = sent[0]
    assert "Welcome to Homeland" in data["text"]

    buttons = [btn["text"] for row in data["reply_markup"]["inline_keyboard"] for btn in row]
    assert buttons == ["🔑 Buy Subscription", "♻️ Renew Service", "🛍 My Services", "📚 Tutorial & Support"]


@pytest.mark.asyncio
async def test_start_shows_admin_button_for_admin(dispatcher, bot, fake_session):
    update = make_message_update(FAKE_ADMIN_ID, "/start")
    await dispatcher.feed_update(bot, update)

    _, data = [call for call in fake_session.calls if call[0] == "sendMessage"][0]
    buttons = [btn["text"] for row in data["reply_markup"]["inline_keyboard"] for btn in row]
    assert "🛠 Admin Panel" in buttons


@pytest.mark.asyncio
async def test_placeholder_callbacks_answer_coming_soon(dispatcher, bot, fake_session):
    for callback_data in ("menu:buy", "menu:renew", "menu:myservices", "menu:tutorials"):
        fake_session.reset()
        update = make_callback_update(999, callback_data)
        await dispatcher.feed_update(bot, update)

        answered = [call for call in fake_session.calls if call[0] == "answerCallbackQuery"]
        assert len(answered) == 1
        assert "coming soon" in answered[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_menu_root_callback_redraws_main_menu(dispatcher, bot, fake_session):
    update = make_callback_update(999, "menu:root")
    await dispatcher.feed_update(bot, update)

    edited = [call for call in fake_session.calls if call[0] == "editMessageText"]
    assert len(edited) == 1
    assert "Welcome to Homeland" in edited[0][1]["text"]


@pytest.mark.asyncio
async def test_unrecognized_message_falls_back_to_main_menu(dispatcher, bot, fake_session):
    update = make_message_update(999, "gibberish")
    await dispatcher.feed_update(bot, update)

    sent = [call for call in fake_session.calls if call[0] == "sendMessage"]
    assert len(sent) == 1
    assert "Welcome to Homeland" in sent[0][1]["text"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bot.keyboards'`.

- [ ] **Step 3: Write the keyboards**

```python
# app/bot/keyboards/__init__.py
```

```python
# app/bot/keyboards/menus.py
"""Button-builder functions for the main menu and shared back controls.
Pure keyboard builders only - no handler logic here."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(*, is_admin: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    builder.button(text="🔑 Buy Subscription", callback_data="menu:buy", style="success")
    builder.button(text="♻️ Renew Service", callback_data="menu:renew", style="success")
    builder.button(text="🛍 My Services", callback_data="menu:myservices", style="primary")
    builder.button(text="📚 Tutorial & Support", callback_data="menu:tutorials", style="primary")
    sizes += [2, 2]

    if is_admin:
        builder.button(text="🛠 Admin Panel", callback_data="adm:root")
        sizes.append(1)

    builder.adjust(*sizes)
    return builder.as_markup()
```

- [ ] **Step 4: Write the handlers**

```python
# app/bot/handlers/__init__.py
```

```python
# app/bot/handlers/users.py
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.menus import main_menu
from app.db.session import async_session_maker
from app.services.admin_users import has_level

router = Router(name="users")

WELCOME_TEXT = "👋 Welcome to Homeland VPN.\n\nChoose an option below:"
PLACEHOLDER_TEXT = "🚧 This feature is coming soon."

_PLACEHOLDER_CALLBACKS = {"menu:buy", "menu:renew", "menu:myservices", "menu:tutorials"}


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


async def send_main_menu(target: Message) -> None:
    is_admin = await _is_admin(target.from_user.id) if target.from_user else False
    await target.answer(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin))


@router.message(Command("start"))
async def start_cmd(message: Message) -> None:
    await send_main_menu(message)


@router.callback_query(F.data == "menu:root")
async def menu_root_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        is_admin = await _is_admin(callback.from_user.id)
        await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin))
    await callback.answer()


@router.callback_query(F.data.in_(_PLACEHOLDER_CALLBACKS))
async def placeholder_cb(callback: CallbackQuery) -> None:
    await callback.answer(PLACEHOLDER_TEXT, show_alert=True)
```

```python
# app/bot/handlers/fallback.py
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.handlers.users import send_main_menu

router = Router(name="fallback")


@router.message()
async def fallback_to_main_menu(message: Message, state: FSMContext) -> None:
    """Registered last in main.py, after every other router - only ever
    reached once no command/state-specific handler claimed the message
    first. Shows the main menu unless the user has an FSM state in
    progress, in which case some state-specific handler already had
    first refusal and this isn't the place to guess at what they meant."""
    if await state.get_state() is not None:
        return
    await send_main_menu(message)
```

```python
# app/bot/error_handlers.py
"""Global aiogram error handler - registered once in main.py via
dp.errors.register(...). Handles a DB connection-pool timeout with a
clear message instead of the unhandled-exception path every other
error still takes."""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

logger = logging.getLogger(__name__)

_POOL_BUSY_MESSAGE = "⏳ The server is temporarily busy. Please try again shortly."


async def handle_pool_timeout(event: ErrorEvent) -> bool:
    if not isinstance(event.exception, PoolTimeoutError):
        return False

    inner: Message | CallbackQuery | None = event.update.message or event.update.callback_query
    chat_id = None
    if isinstance(inner, Message):
        chat_id = inner.chat.id
    elif isinstance(inner, CallbackQuery) and inner.message is not None:
        chat_id = inner.message.chat.id

    logger.warning("DB connection pool exhausted (update_id=%s, chat_id=%s)", event.update.update_id, chat_id)

    if chat_id is not None:
        try:
            await event.update.bot.send_message(chat_id, _POOL_BUSY_MESSAGE)
        except Exception:
            logger.exception("Could not deliver the pool-busy message to chat_id=%s", chat_id)
    return True
```

- [ ] **Step 5: Extend the `dispatcher` fixture in `tests/conftest.py`**

Replace the `dispatcher` fixture body:

```python
@pytest_asyncio.fixture(scope="session")
async def dispatcher():
    """The real Dispatcher, wired like app.main.main() does - built out
    incrementally as later plans add routers/middlewares. Session-scoped:
    aiogram Router objects are module-level singletons and refuse to
    attach to more than one Dispatcher. Safe to share across the whole
    session because every test uses a distinct telegram_id."""
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    from app.bot.handlers import fallback, users
    from app.bot.middlewares.blocked_user import BlockedUserMiddleware
    from app.bot.middlewares.private_chat_only import PrivateChatOnlyMiddleware
    from app.bot.middlewares.user_tracking import UserTrackingMiddleware

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(PrivateChatOnlyMiddleware())
    dp.update.outer_middleware(UserTrackingMiddleware())
    dp.update.outer_middleware(BlockedUserMiddleware())

    dp.include_router(users.router)
    dp.include_router(fallback.router)
    return dp
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `make test`
Expected: PASS — 5 tests in `test_start_and_menu.py`, plus everything from Tasks 1-7.

- [ ] **Step 7: Commit**

```bash
git add app/bot/keyboards app/bot/handlers app/bot/error_handlers.py tests/conftest.py tests/functional/test_start_and_menu.py
git commit -m "feat: minimal bot - English main menu with placeholder actions"
```

---

## Task 9: Wire the real app service, entrypoint, and docs

**Files:**
- Create: `app/main.py`
- Modify: `docker-compose.yml` (add the `bot` service)
- Create: `CLAUDE.md`, `README.md`

**Interfaces:**
- Consumes: everything from Tasks 1-8.
- Produces: a runnable `python -m app.main` entrypoint; a buildable Docker image.

- [ ] **Step 1: Write `app/main.py`**

```python
# app/main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand

from app.bot.error_handlers import handle_pool_timeout
from app.bot.handlers import fallback, users
from app.bot.middlewares.blocked_user import BlockedUserMiddleware
from app.bot.middlewares.private_chat_only import PrivateChatOnlyMiddleware
from app.bot.middlewares.user_tracking import UserTrackingMiddleware
from app.config import get_settings

settings = get_settings()

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)
    dp.errors.register(handle_pool_timeout)
    dp.update.outer_middleware(PrivateChatOnlyMiddleware())
    dp.update.outer_middleware(UserTrackingMiddleware())
    dp.update.outer_middleware(BlockedUserMiddleware())

    dp.include_router(users.router)
    dp.include_router(fallback.router)

    await bot.set_my_commands([BotCommand(command="start", description="Start / main menu")])
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Add the `bot` service to `docker-compose.yml`**

Insert before the `db:` service:

```yaml
  bot:
    build: .
    env_file: .env
    networks:
      - default
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
```

And add a top-level `networks:` section if not already present:

```yaml
networks:
  default:
```

- [ ] **Step 3: Verify the image builds**

Run: `docker compose build bot`
Expected: exits 0.

- [ ] **Step 4: Write `CLAUDE.md`**

```markdown
# CLAUDE.md

Homeland - a Telegram bot selling reverse VPN (Iran-based IPs) in USD to
Iranian customers abroad. Bootstrapped from AloBot (`/Users/peyman/telegram-bot`,
a sibling project selling the opposite direction of VPN in Toman), trimmed
to a flat 4-plan catalog with English-only text and Stripe/crypto payments.
See `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` for the full
design and `docs/superpowers/plans/` for implementation plans.

## Stack
Python 3.12+, aiogram 3.x (async), PostgreSQL + SQLAlchemy 2.0 + Alembic,
Redis (FSM), pydantic-settings, Docker Compose.

## Architecture
- `app/bot/handlers/` - one router per domain, registered in `app/main.py`.
- `app/services/ibsng/client.py` - the ONLY place that calls the IBSng API.
  Same server AloBot uses, Homeland's own ISP name/credentials/groups.
  `user_balance.getUserBalanceInfoByUserID` is confirmed dead on this
  server - never use it; see the module docstring and spec §5/§14 for the
  quota-data plan instead.
- `app/db/models/plan.py` - the 4 fixed sale plans (2 Weeks/1 Month/2
  Months/3 Months), seeded via migration `0002_catalog.py`. No category/
  location/user-count matrix like AloBot's `Service` - see spec §4.
- `app/config.py` - single `Settings` source of truth, loaded from `.env`.
  No hardcoded secrets, ever.
- FSM state lives in Redis (`app/redis.py`).

## Conventions
- Async only - no blocking I/O in handlers or services.
- Type hints on every function signature.
- All user-facing AND admin-facing strings in English.
- IBSng operations (create/renew user) must be idempotent.
- Keep handlers thin: parse input, call a service, reply.
- New feature = new router + new service method, not a growing god-file.
- Every interactive flow/menu includes a "Back" button by default.

## Commands
`make setup` (generate .env) · `make up` / `make down` · `make migrate` ·
`make logs` · `make bot` (run locally) · `make test` (isolated test stack)
```

- [ ] **Step 5: Write `README.md`**

```markdown
# Homeland Bot

Telegram bot selling reverse VPN (Iran-based IP addresses) in USD to
Iranian customers living outside Iran. Backend provisioning/accounting is
IBSng (same server as the sibling AloBot project, separate ISP/groups).

## Status

This is the bootstrap/foundation slice: repo scaffold, config, DB/Redis,
the ported IBSng client, the 4-plan catalog, and a main menu that shows
all 4 buttons with "coming soon" placeholders. Buy/Renew/My Services/
Tutorial & Support/Admin Panel are implemented in follow-up plans under
`docs/superpowers/plans/`.

## Setup

```bash
make setup    # interactive .env generator
make up       # docker compose up -d --build
make migrate  # apply database migrations
```

## Testing

Fully isolated stack (own Postgres/Redis, in-process fake IBSng XML-RPC
server and fake Telegram session - nothing reaches production or real
Telegram):

```bash
make test
```

## Design docs

- `docs/superpowers/specs/2026-09-14-homeland-bot-design.md` - full design
- `docs/superpowers/plans/2026-09-14-homeland-bootstrap.md` - this slice's plan
```

- [ ] **Step 6: Run the full test suite one last time**

Run: `make test`
Expected: PASS — every test from Tasks 1-8, nothing broken by the `main.py`/compose changes.

- [ ] **Step 7: Commit**

```bash
git add app/main.py docker-compose.yml CLAUDE.md README.md
git commit -m "feat: entrypoint, bot service in docker-compose, project docs"
```

---

## What this plan deliberately does not build

Buy/Renew/My Services (including real quota reading), Tutorial & Support
content, ToS/Privacy delivery, reminders, the payment provider
abstraction (Stripe/crypto), and the admin panel (broadcast, discount
codes, sales reports, service/user ops) are all separate follow-up plans
per the spec's own subsystem breakdown (spec §2.3, §6, §7, §8, §9, §10) -
each is independently testable and none of them are needed for this
plan's bot to run and pass its own tests.
