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

    # NOWPayments - config placeholders only, no live keys yet.
    # create_crypto_payment raises PaymentProviderNotConfiguredError while
    # nowpayments_api_key is blank, so the bot can run today with crypto
    # payment visibly unavailable until real keys are provisioned.
    #
    # Settlement/outcome currency (USDT on TRC-20, primary) is configured
    # in the NOWPayments dashboard itself (payout wallet address) - not
    # in code, and not something this app ever needs to know about.
    nowpayments_api_key: str = ""
    nowpayments_ipn_secret: str = ""
    nowpayments_ipn_callback_url: str = ""

    # Coins a customer may pay with, as NOWPayments currency codes, in the
    # order the payment chooser lists them. Each must also be enabled in
    # the NOWPayments dashboard's coin settings. Extend here (e.g. add
    # ",ton") - never hardcode a per-coin minimum anywhere: minimums come
    # live from GET /v1/min-amount, see app/services/payments/minimums.py.
    nowpayments_pay_currencies: str = "usdttrc20,usdtbsc,trx,ltc"

    # The coin our NOWPayments payout wallet settles in. Used as
    # min-amount's currency_to: a coin's real minimum is the minimum for
    # converting it INTO this currency. Verified live on 2026-09-21 -
    # omitting currency_to does NOT fall back to the dashboard wallet as
    # the API docs claim; it prices the coin against itself and reported
    # TRX at $0.25 instead of its true $12.31, which would have offered
    # TRX for plans it cannot actually pay. Change this only if the
    # dashboard payout wallet changes.
    nowpayments_settlement_currency: str = "usdttrc20"

    # Used only to build NOWPayments' optional success_url/cancel_url
    # (a deep link back into the bot after the hosted payment page) -
    # blank means those params are simply omitted from the invoice
    # request; NOWPayments shows its own default confirmation page
    # instead. Real confirmation always happens via the IPN-triggered
    # Telegram message regardless, so this is cosmetic only.
    bot_username: str = ""

    @property
    def nowpayments_pay_currency_list(self) -> list[str]:
        return [code.strip().lower() for code in self.nowpayments_pay_currencies.split(",") if code.strip()]

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
