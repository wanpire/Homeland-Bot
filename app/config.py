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

    # Plisio - ONE secret key authenticates API calls AND signs callbacks;
    # there is no separate IPN secret. create_crypto_payment raises
    # PaymentProviderNotConfiguredError while this is blank, so the bot
    # runs with crypto visibly unavailable until a key is provisioned.
    plisio_secret_key: str = ""

    # Full public URL Plisio POSTs invoice updates to. MUST carry
    # ?json=true: without it Plisio sends a PHP-serialized form post whose
    # verify_hash this app cannot reproduce - see the migration spec §3.
    plisio_callback_url: str = ""

    # Coins the buyer may pay with, as Plisio currency IDs (the ID column
    # of Plisio's Supported cryptocurrencies table), sent as
    # allowed_psys_cids so the buyer picks one on Plisio's invoice page.
    # Each must also have a wallet configured on the Plisio account.
    plisio_pay_currencies: str = "LTC,TON,USDT_TON,USDT_TRX,TRX"

    # Telegram chat id of the operational log group (negative for a
    # supergroup). A string rather than an int so "unset" needs no
    # sentinel number; blank disables every operational log entry, which
    # keeps the feature opt-in and leaves local runs untouched.
    admin_log_chat_id: str = ""

    # Used only to build Plisio's optional success_invoice_url /
    # fail_invoice_url (a deep link back into the bot from the hosted
    # invoice page) - blank means those params are simply omitted. Real
    # confirmation always happens via the callback-triggered Telegram
    # message regardless, so this is cosmetic only.
    bot_username: str = ""

    @property
    def plisio_pay_currency_list(self) -> list[str]:
        return [code.strip().upper() for code in self.plisio_pay_currencies.split(",") if code.strip()]

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
