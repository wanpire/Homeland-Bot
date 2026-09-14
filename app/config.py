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
