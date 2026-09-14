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
