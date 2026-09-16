# Crypto Payment (NOWPayments) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Buy Subscription's and Renew Service's "payment coming soon" walls with a real crypto payment path via NOWPayments' hosted Invoice API: create an invoice, hand the buyer a link, and activate the service only once a signed IPN webhook reports `finished`.

**Architecture:** A new `Payment`/`PaymentStatusEvent` data model, a `PaymentProvider` abstraction (two methods only — `create_invoice`/`verify_webhook`) implemented by `CryptoProvider` wrapping a thin NOWPayments HTTP client, a Homeland-domain `service.py` that creates payments and activates them via the existing `create_vpn_user`/`renew_and_change_group` functions, and an `aiohttp` webhook server running in the same process as the bot's polling loop.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, PostgreSQL, aiohttp (webhook server), httpx (NOWPayments client — already a dependency), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-16-crypto-payment-design.md`

## Global Constraints

- Exactly one idempotency gate for `Payment.status`: `if payment.status != "pending": return` (ignore) in the webhook route. No other code path may change `Payment.status`. (Spec §9, §11.)
- `PaymentProvider` has exactly two abstract methods — `create_invoice`, `verify_webhook`. There is no `on_payment_confirmed` on the interface; activation logic (`create_vpn_user`/`renew_and_change_group`) lives only in `app/services/payments/service.py`, never inside a provider class. This is a deliberate correction of the parent spec, not an oversight — see spec §4. (Spec §4.)
- `Payment.paid_amount`, `PaymentStatusEvent.paid_amount`, and `WebhookEvent.paid_amount` are all in the invoice's pay_currency (crypto units, e.g. USDT) — **never USD**. Never compute or display a USD shortfall from this value; a partial-payment message must not fabricate a dollar figure. (Spec §9.)
- Every id parsed from an external, attacker-reachable source — Telegram callback_data OR an IPN's `order_id` — must be guarded against both non-numeric AND out-of-PostgreSQL-int4-range values before being used in a query, degrading to "ignored"/not-found rather than raising. This project's own established lesson (found and fixed in the Renew Service feature's final review), reapplied here for the webhook route. (Spec §9, §11.)
- Signature verification happens before any DB read in the webhook route; an invalid HMAC returns 401 immediately, no payload parsing, no DB access. (Spec §9, §11.)
- All user-facing text is English-only. (Project-wide convention, `CLAUDE.md`.)
- No Stripe code in this plan. `stripe_api_key`/`stripe_webhook_secret` in `app/config.py` stay exactly as they are today — untouched, unused. (Spec §5, §12.)
- `create_invoice` must raise `PaymentProviderNotConfiguredError` (not a raw API failure) when `nowpayments_api_key` is blank, so the bot can run with crypto payment visibly unavailable until real keys are provisioned. (Spec §6.)

---

## File Structure

- **Create** `app/db/models/payment.py` — the `Payment` model.
- **Create** `app/db/models/payment_status_event.py` — the `PaymentStatusEvent` model.
- **Modify** `app/db/models/__init__.py` — register both new models.
- **Create** `alembic/versions/0007_payments.py` — migration for both tables.
- **Modify** `app/config.py` — rename crypto placeholders to NOWPayments-specific names, add `bot_username`.
- **Modify** `app/services/discounts.py` — add `increment_discount_usage`.
- **Modify** `tests/conftest.py` — add NOWPayments test-default env vars.
- **Modify** `tests/unit/test_config.py` — fix the stale `CRYPTO_GATEWAY_` env-var prefix filter.
- **Create** `app/services/payments/__init__.py` — empty, makes it a package.
- **Create** `app/services/payments/nowpayments.py` — the NOWPayments HTTP client.
- **Create** `app/services/payments/base.py` — `PaymentProvider` ABC, `WebhookEvent`.
- **Create** `app/services/payments/crypto_provider.py` — `CryptoProvider`.
- **Create** `app/services/payments/service.py` — `create_crypto_payment`, `activate_finished_payment`.
- **Create** `app/webhook.py` — the aiohttp IPN receiver.
- **Modify** `app/main.py` — start the webhook server alongside polling.
- **Modify** `docker-compose.yml` — expose `webhook_port`.
- **Modify** `app/bot/keyboards/buy.py` — relabel the Buy button, add `payment_link_keyboard`.
- **Modify** `app/bot/handlers/buy.py` — `buy_confirm_cb` creates a real payment.
- **Modify** `app/bot/keyboards/renew.py` — relabel the Renew button.
- **Modify** `app/bot/handlers/renew.py` — `renew_confirm_cb` creates a real payment.

---

## Task 1: Data model, migration, config, and discount usage tracking

**Files:**
- Create: `app/db/models/payment.py`
- Create: `app/db/models/payment_status_event.py`
- Modify: `app/db/models/__init__.py`
- Create: `alembic/versions/0007_payments.py`
- Modify: `app/config.py`
- Modify: `app/services/discounts.py`
- Modify: `tests/conftest.py`
- Modify: `tests/unit/test_config.py`
- Test: `tests/functional/test_payment_model.py`
- Test: `tests/functional/test_discounts.py`

**Interfaces:**
- Produces: `Payment` (SQLAlchemy model, `app/db/models/payment.py`, fields: `id, telegram_id, purpose, vpn_user_id, plan_id, discount_code_id, group_name, data_cap_mb, ibsng_username, ibsng_password, amount_usd, original_amount_usd, paid_amount, provider, provider_payment_id, invoice_url, status, created_at, resolved_at`), `PaymentStatusEvent` (`app/db/models/payment_status_event.py`, fields: `id, payment_id, raw_status, paid_amount, created_at`), `Settings.nowpayments_api_key: str`, `Settings.nowpayments_ipn_secret: str`, `Settings.nowpayments_ipn_callback_url: str`, `Settings.bot_username: str` (all `app/config.py`), `increment_discount_usage(session: AsyncSession, discount_code_id: int) -> None` (`app/services/discounts.py`). Every later task depends on the `Payment` model; Task 3 depends on `increment_discount_usage`.

- [ ] **Step 1: Write the failing test for the `Payment` model**

Create `tests/functional/test_payment_model.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_create_payment_row_defaults(seeded_catalog: dict) -> None:
    from app.db.models.payment import Payment

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        payment = Payment(
            telegram_id=900,
            purpose="purchase",
            plan_id=plan_id,
            group_name="1M-1U-Iran-10G",
            data_cap_mb=10240,
            amount_usd=Decimal("5.00"),
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)

    assert payment.id is not None
    assert payment.status == "pending"
    assert payment.provider == "nowpayments"
    assert payment.vpn_user_id is None
    assert payment.discount_code_id is None
    assert payment.provider_payment_id is None
    assert payment.paid_amount is None


@pytest.mark.asyncio
async def test_payment_id_must_be_unique_for_provider_payment_id(seeded_catalog: dict) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.db.models.payment import Payment

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        session.add(Payment(
            telegram_id=901, purpose="purchase", plan_id=plan_id, group_name="g", data_cap_mb=1,
            amount_usd=Decimal("5.00"), provider_payment_id="np-123",
        ))
        await session.commit()

    async with async_session_maker() as session:
        session.add(Payment(
            telegram_id=902, purpose="purchase", plan_id=plan_id, group_name="g", data_cap_mb=1,
            amount_usd=Decimal("5.00"), provider_payment_id="np-123",
        ))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_payment_status_event_links_to_payment(seeded_catalog: dict) -> None:
    from app.db.models.payment import Payment
    from app.db.models.payment_status_event import PaymentStatusEvent

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        payment = Payment(
            telegram_id=903, purpose="purchase", plan_id=plan_id, group_name="g", data_cap_mb=1,
            amount_usd=Decimal("5.00"),
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)

        session.add(PaymentStatusEvent(payment_id=payment.id, raw_status="waiting"))
        await session.commit()

        rows = (
            await session.execute(select(PaymentStatusEvent).where(PaymentStatusEvent.payment_id == payment.id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].raw_status == "waiting"
    assert rows[0].paid_amount is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_payment_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db.models.payment'`

- [ ] **Step 3: Create `app/db/models/payment.py`**

```python
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Payment(Base):
    """One crypto payment attempt for one plan, tied either to a new
    purchase (purpose="purchase", vpn_user_id starts NULL, set once
    create_vpn_user succeeds) or a renewal of an existing owned service
    (purpose="renew", vpn_user_id set at creation time and never
    changes). group_name/data_cap_mb are snapshotted from the Plan at
    creation time - not re-derived from plan_id later - so an admin
    editing the catalog mid-payment can never retroactively change what
    a pending payment provisions, mirroring VPNUser.data_cap_mb's own
    snapshot rationale (see that model's docstring).

    status is Homeland's own coarse view (pending/paid/partially_paid/
    failed/refunded), separate from the raw NOWPayments payment_status
    strings recorded per-IPN in PaymentStatusEvent - never conflate the
    two: NOWPayments has finer states (waiting/confirming/sending) that
    don't need their own Payment.status value, since nothing user-facing
    or provisioning-related happens until "finished"."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # "purchase" | "renew"
    vpn_user_id: Mapped[int | None] = mapped_column(ForeignKey("vpn_users.id"), nullable=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    discount_code_id: Mapped[int | None] = mapped_column(
        ForeignKey("discount_codes.id", ondelete="SET NULL"), nullable=True
    )

    group_name: Mapped[str] = mapped_column(String(64))
    data_cap_mb: Mapped[int] = mapped_column(Integer)

    # Only set for purpose="purchase" - a renew targets an existing,
    # already-credentialed account (vpn_user_id above), so these stay
    # NULL for purpose="renew".
    ibsng_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ibsng_password: Mapped[str | None] = mapped_column(String(128), nullable=True)

    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # NOWPayments' IPN "actually_paid" field, in the invoice's pay_currency
    # (e.g. USDT) - NOT necessarily USD, despite amount_usd/original_amount_usd
    # above being USD. Never presented to a user as a dollar figure (see
    # app/webhook.py's partially_paid handling) - stored for audit/support
    # cross-reference against the NOWPayments dashboard only.
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    provider: Mapped[str] = mapped_column(String(16), default="nowpayments")
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # pending -> paid | partially_paid | failed | refunded
    status: Mapped[str] = mapped_column(String(16), default="pending")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Create `app/db/models/payment_status_event.py`**

```python
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentStatusEvent(Base):
    """One row per IPN delivery received for a Payment - an append-only
    audit trail of every raw NOWPayments payment_status this project has
    ever seen for that payment, independent of Payment.status (which
    only tracks Homeland's own coarse view). Never updated or deleted."""

    __tablename__ = "payment_status_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    raw_status: Mapped[str] = mapped_column(String(32))
    # Same caveat as Payment.paid_amount - NOWPayments' pay_currency units,
    # not USD.
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: Register both models in `app/db/models/__init__.py`**

Change:

```python
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser
from app.db.models.discount_code import DiscountCode
from app.db.models.group import Group
from app.db.models.openvpn_profile import OpenVpnProfile
from app.db.models.plan import Plan
from app.db.models.tutorial_guide import TutorialGuide
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser

__all__ = [
    "AdminUser", "AppConfig", "BotUser", "DiscountCode", "Group", "OpenVpnProfile", "Plan",
    "TutorialGuide", "TutorialPlatform", "TutorialProtocol", "VPNUser",
]
```

to:

```python
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser
from app.db.models.discount_code import DiscountCode
from app.db.models.group import Group
from app.db.models.openvpn_profile import OpenVpnProfile
from app.db.models.payment import Payment
from app.db.models.payment_status_event import PaymentStatusEvent
from app.db.models.plan import Plan
from app.db.models.tutorial_guide import TutorialGuide
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser

__all__ = [
    "AdminUser", "AppConfig", "BotUser", "DiscountCode", "Group", "OpenVpnProfile", "Payment",
    "PaymentStatusEvent", "Plan", "TutorialGuide", "TutorialPlatform", "TutorialProtocol", "VPNUser",
]
```

- [ ] **Step 6: Create the migration `alembic/versions/0007_payments.py`**

```python
"""payments and payment_status_events tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("vpn_user_id", sa.Integer(), sa.ForeignKey("vpn_users.id"), nullable=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column(
            "discount_code_id", sa.Integer(), sa.ForeignKey("discount_codes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("group_name", sa.String(64), nullable=False),
        sa.Column("data_cap_mb", sa.Integer(), nullable=False),
        sa.Column("ibsng_username", sa.String(64), nullable=True),
        sa.Column("ibsng_password", sa.String(128), nullable=True),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("original_amount_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("paid_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("provider", sa.String(16), nullable=False, server_default="nowpayments"),
        sa.Column("provider_payment_id", sa.String(64), nullable=True),
        sa.Column("invoice_url", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payments_telegram_id", "payments", ["telegram_id"])
    op.create_index("ix_payments_provider_payment_id", "payments", ["provider_payment_id"], unique=True)

    op.create_table(
        "payment_status_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("raw_status", sa.String(32), nullable=False),
        sa.Column("paid_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payment_status_events_payment_id", "payment_status_events", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_status_events_payment_id", table_name="payment_status_events")
    op.drop_table("payment_status_events")
    op.drop_index("ix_payments_provider_payment_id", table_name="payments")
    op.drop_index("ix_payments_telegram_id", table_name="payments")
    op.drop_table("payments")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/functional/test_payment_model.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add app/db/models/payment.py app/db/models/payment_status_event.py app/db/models/__init__.py \
        alembic/versions/0007_payments.py tests/functional/test_payment_model.py
git commit -m "feat: add Payment and PaymentStatusEvent models + migration"
```

- [ ] **Step 9: Fix the stale `CRYPTO_GATEWAY_` prefix filter in `tests/unit/test_config.py`**

This must happen before the new config test below: `_isolated_env` (an autouse fixture in this file) clears specific env-var prefixes before each test in it runs, and without this fix it would leave `NOWPAYMENTS_API_KEY` (set process-wide by Step 10 below) unclear, making the "defaults are blank" test in Step 12 see the wrong value.

Change:

```python
        if key.startswith(("BOT_TOKEN", "ADMIN_IDS", "IBSNG_", "POSTGRES_", "REDIS_", "STRIPE_", "CRYPTO_GATEWAY_")):
```

to:

```python
        if key.startswith(("BOT_TOKEN", "ADMIN_IDS", "IBSNG_", "POSTGRES_", "REDIS_", "STRIPE_", "NOWPAYMENTS_")):
```

- [ ] **Step 10: Add NOWPayments test-default env vars to `tests/conftest.py`**

In the `_REQUIRED_TEST_ENV` dict near the top of `tests/conftest.py`, add two entries (keep every existing entry as-is):

```python
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
    "NOWPAYMENTS_API_KEY": "test-nowpayments-api-key",
    "NOWPAYMENTS_IPN_SECRET": "test-nowpayments-ipn-secret",
}
```

This makes the happy-path crypto payment flow exercised by default in every functional test (a real, non-blank key) — needed starting with Task 2's client tests. A test that specifically needs the "not configured" fallback path monkeypatches the cached settings instance directly instead of touching this dict:

```python
from app.config import get_settings
monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")
```

(`get_settings()` is `@lru_cache`'d and returns the same mutable `Settings` instance every call, so this scopes to one test only - `monkeypatch` restores the original value automatically at teardown - with no env-var/cache-clear side effects on any other test in the session.) `pydantic-settings` ignores unrecognized env vars (`Settings.model_config` sets `extra="ignore"`), so setting `NOWPAYMENTS_API_KEY` here is safe even though `app/config.py` doesn't have a matching field yet — that's added next.

- [ ] **Step 11: Write the failing test for the config rename**

Append to `tests/unit/test_config.py`:

```python
def test_settings_nowpayments_fields_default_blank() -> None:
    from app.config import get_settings

    settings = get_settings()
    assert settings.nowpayments_api_key == ""
    assert settings.nowpayments_ipn_secret == ""
    assert settings.bot_username == ""
```

- [ ] **Step 12: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py::test_settings_nowpayments_fields_default_blank -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'nowpayments_api_key'`

- [ ] **Step 13: Rename and extend config settings**

In `app/config.py`, change:

```python
    # Stripe - config placeholders only, no live keys yet (see spec §6).
    # create_invoice raises PaymentProviderNotConfiguredError while blank.
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""

    # Crypto gateway - config placeholders only, no live keys yet.
    crypto_gateway_api_key: str = ""
    crypto_gateway_ipn_secret: str = ""
    crypto_gateway_ipn_callback_url: str = ""
```

to:

```python
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

    # Used only to build NOWPayments' optional success_url/cancel_url
    # (a deep link back into the bot after the hosted payment page) -
    # blank means those params are simply omitted from the invoice
    # request; NOWPayments shows its own default confirmation page
    # instead. Real confirmation always happens via the IPN-triggered
    # Telegram message regardless, so this is cosmetic only.
    bot_username: str = ""
```

(`webhook_port: int = 8090` above this block is unchanged - it already exists and is reused as-is.)

- [ ] **Step 14: Run the full config test file**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS (7 tests: the 6 pre-existing plus the new one)

- [ ] **Step 15: Commit**

```bash
git add app/config.py tests/conftest.py tests/unit/test_config.py
git commit -m "feat: rename crypto config placeholders to NOWPayments-specific names"
```

- [ ] **Step 16: Write the failing test for `increment_discount_usage`**

Append to `tests/functional/test_discounts.py`:

```python
@pytest.mark.asyncio
async def test_increment_discount_usage_increases_used_count() -> None:
    from app.services.discounts import increment_discount_usage

    async with async_session_maker() as session:
        discount = await create_discount_code(
            session, code="BUMP10", percent=Decimal("10"), usage_limit=None, plan_ids=None,
        )
    assert discount.used_count == 0

    async with async_session_maker() as session:
        await increment_discount_usage(session, discount.id)

    async with async_session_maker() as session:
        refreshed = await get_discount_code(session, discount.id)
    assert refreshed.used_count == 1
```

- [ ] **Step 17: Run test to verify it fails**

Run: `pytest tests/functional/test_discounts.py::test_increment_discount_usage_increases_used_count -v`
Expected: FAIL with `ImportError: cannot import name 'increment_discount_usage'`

- [ ] **Step 18: Implement `increment_discount_usage`**

Append to `app/services/discounts.py` (after `find_best_auto_discount`, the last function in the file):

```python
async def increment_discount_usage(session: AsyncSession, discount_code_id: int) -> None:
    """Called once per finished payment that applied a discount - see
    app/services/payments/service.py's activate_finished_payment. The
    docstring on DiscountCode.used_count has said since Admin Panel
    shipped that this call was coming; this is it."""
    discount = await session.get(DiscountCode, discount_code_id)
    if discount is None:
        return
    discount.used_count += 1
    await session.commit()
```

- [ ] **Step 19: Run tests to verify they pass**

Run: `pytest tests/functional/test_discounts.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 20: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green.

- [ ] **Step 21: Commit**

```bash
git add app/services/discounts.py tests/functional/test_discounts.py
git commit -m "feat: add increment_discount_usage for finished crypto payments"
```

---

## Task 2: NOWPayments client

**Files:**
- Create: `app/services/payments/__init__.py`
- Create: `app/services/payments/nowpayments.py`
- Test: `tests/functional/test_nowpayments_client.py`

**Interfaces:**
- Consumes: `Settings.nowpayments_api_key`, `Settings.nowpayments_ipn_callback_url`, `Settings.bot_username` (Task 1, `app/config.py`).
- Produces: `async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]` (returns `(invoice_url, payment_id)`), `def verify_ipn_signature(raw_body: bytes, signature: str, ipn_secret: str) -> bool`, `class NowPaymentsError(Exception)`, `class PaymentProviderNotConfiguredError(Exception)` — all `app/services/payments/nowpayments.py`. Task 3's `CryptoProvider` and Task 5's bot handlers both import from this module.

- [ ] **Step 1: Create the empty package file**

Create `app/services/payments/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests for `create_invoice`**

Create `tests/functional/test_nowpayments_client.py`:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._json_data


@pytest.mark.asyncio
async def test_create_invoice_returns_url_and_payment_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-123"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    invoice_url, payment_id = await nowpayments.create_invoice(
        order_id="42", amount=Decimal("5.00"), description="Homeland: 1 Month",
    )

    assert invoice_url == "https://nowpayments.io/payment/abc"
    assert payment_id == "np-123"
    assert captured["url"] == "https://api.nowpayments.io/v1/invoice"
    assert captured["json"]["order_id"] == "42"
    assert captured["json"]["price_amount"] == "5.00"
    assert captured["json"]["price_currency"] == "usd"
    assert captured["headers"]["x-api-key"] == "test-nowpayments-api-key"


@pytest.mark.asyncio
async def test_create_invoice_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import nowpayments

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")

    with pytest.raises(nowpayments.PaymentProviderNotConfiguredError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(500, text="internal error")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_raises_on_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc"})  # missing "id"

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    with pytest.raises(nowpayments.NowPaymentsError):
        await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")


@pytest.mark.asyncio
async def test_create_invoice_includes_optional_callback_and_success_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services.payments import nowpayments

    monkeypatch.setattr(get_settings(), "nowpayments_ipn_callback_url", "https://bot.example.com/webhooks/crypto")
    monkeypatch.setattr(get_settings(), "bot_username", "homelandservice_bot")
    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-1"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")

    assert captured["json"]["ipn_callback_url"] == "https://bot.example.com/webhooks/crypto"
    assert captured["json"]["success_url"] == "https://t.me/homelandservice_bot"
    assert captured["json"]["cancel_url"] == "https://t.me/homelandservice_bot"


@pytest.mark.asyncio
async def test_create_invoice_omits_optional_urls_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments

    captured: dict[str, Any] = {}

    async def _fake_post(self: httpx.AsyncClient, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        captured["json"] = json
        return _FakeResponse(200, {"invoice_url": "https://nowpayments.io/payment/abc", "id": "np-1"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await nowpayments.create_invoice(order_id="1", amount=Decimal("5.00"), description="x")

    assert "ipn_callback_url" not in captured["json"]
    assert "success_url" not in captured["json"]
    assert "cancel_url" not in captured["json"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/functional/test_nowpayments_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.payments.nowpayments'`

- [ ] **Step 4: Create `app/services/payments/nowpayments.py`**

```python
"""Client for NOWPayments' hosted Invoice API. We use the Invoice flow
(not the raw Payment API) so NOWPayments handles coin selection, address
generation, and the QR/payment page entirely - we only need an
invoice_url to hand the buyer and an IPN webhook to hear back. Ported
from the sibling project's app/services/nowpayments.py - see
docs/superpowers/specs/2026-09-16-crypto-payment-design.md.

Reference: https://documenter.getpostman.com/view/7907941/S1a32n38
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import httpx

from app.config import get_settings

_BASE_URL = "https://api.nowpayments.io/v1"


class NowPaymentsError(Exception):
    """Raised when the NOWPayments API returns an error."""


class PaymentProviderNotConfiguredError(Exception):
    """Raised instead of a confusing raw API failure when nowpayments_api_key
    is blank - lets the bot run with crypto payment visibly unavailable
    until real keys are provisioned."""


async def create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
    """Returns (invoice_url, payment_id) - payment_id is NOWPayments'
    own id for this invoice, stored on Payment.provider_payment_id for
    IPN lookup."""
    settings = get_settings()
    if not settings.nowpayments_api_key:
        raise PaymentProviderNotConfiguredError("NOWPAYMENTS_API_KEY is not set")

    payload: dict[str, str] = {
        "price_amount": str(amount),
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": description,
    }
    if settings.nowpayments_ipn_callback_url:
        payload["ipn_callback_url"] = settings.nowpayments_ipn_callback_url
    if settings.bot_username:
        payload["success_url"] = f"https://t.me/{settings.bot_username}"
        payload["cancel_url"] = f"https://t.me/{settings.bot_username}"

    headers = {"x-api-key": settings.nowpayments_api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{_BASE_URL}/invoice", json=payload, headers=headers)

    if response.status_code >= 400:
        raise NowPaymentsError(f"NOWPayments invoice creation failed: {response.status_code} {response.text}")

    data = response.json()
    invoice_url = data.get("invoice_url")
    payment_id = data.get("id")
    if not invoice_url or not payment_id:
        raise NowPaymentsError(f"NOWPayments response missing invoice_url/id: {data!r}")
    return invoice_url, str(payment_id)


def verify_ipn_signature(raw_body: bytes, signature: str, ipn_secret: str) -> bool:
    """NOWPayments signs a sorted-keys JSON encoding of the IPN payload
    with HMAC-SHA512 using the IPN secret (separate from the API key) -
    exact technique ported from the sibling project's nowpayments.py."""
    if not signature:
        return False
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return False
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(ipn_secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/functional/test_nowpayments_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Write the failing tests for `verify_ipn_signature`**

Append to `tests/functional/test_nowpayments_client.py`:

```python
def test_verify_ipn_signature_accepts_correctly_signed_payload() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.services.payments import nowpayments

    payload = {"order_id": "42", "payment_status": "finished"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac_module.new(b"test-secret", canonical.encode(), hashlib.sha512).hexdigest()

    assert nowpayments.verify_ipn_signature(raw_body, signature, "test-secret") is True


def test_verify_ipn_signature_rejects_wrong_secret() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.services.payments import nowpayments

    payload = {"order_id": "42"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac_module.new(b"right-secret", canonical.encode(), hashlib.sha512).hexdigest()

    assert nowpayments.verify_ipn_signature(raw_body, signature, "wrong-secret") is False


def test_verify_ipn_signature_rejects_empty_signature() -> None:
    from app.services.payments import nowpayments

    assert nowpayments.verify_ipn_signature(b'{"a": 1}', "", "secret") is False


def test_verify_ipn_signature_rejects_malformed_json() -> None:
    from app.services.payments import nowpayments

    assert nowpayments.verify_ipn_signature(b"not json", "abc123", "secret") is False
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/functional/test_nowpayments_client.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 8: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green.

- [ ] **Step 9: Commit**

```bash
git add app/services/payments/__init__.py app/services/payments/nowpayments.py tests/functional/test_nowpayments_client.py
git commit -m "feat: add NOWPayments hosted-invoice client"
```

---

## Task 3: PaymentProvider abstraction and payments service

**Files:**
- Create: `app/services/payments/base.py`
- Create: `app/services/payments/crypto_provider.py`
- Create: `app/services/payments/service.py`
- Test: `tests/functional/test_payments_service.py`

**Interfaces:**
- Consumes: `nowpayments.create_invoice`, `nowpayments.verify_ipn_signature`, `nowpayments.NowPaymentsError`, `nowpayments.PaymentProviderNotConfiguredError` (Task 2, `app/services/payments/nowpayments.py`); `Payment` (Task 1, `app/db/models/payment.py`); `increment_discount_usage` (Task 1, `app/services/discounts.py`); `find_best_auto_discount`, `discount_price` (existing, `app/services/discounts.py`); `create_vpn_user`, `generate_vpn_credentials`, `renew_and_change_group`, `VPNUsernameTakenError` (existing, `app/services/vpn_users.py`); `IBSngClient` (existing, `app/services/ibsng/client.py`); `VPNUser`, `Plan` (existing models).
- Produces: `class WebhookEvent` (dataclass, `app/services/payments/base.py`, fields `provider_payment_id: str, order_id: str, raw_status: str, paid_amount: Decimal | None`), `class PaymentProvider(ABC)` (same file, two abstract methods `create_invoice`/`verify_webhook`), `class CryptoProvider(PaymentProvider)` (`app/services/payments/crypto_provider.py`), `async def create_crypto_payment(session: AsyncSession, *, telegram_id: int, purpose: str, plan: Plan, vpn_user: VPNUser | None) -> Payment` and `async def activate_finished_payment(session: AsyncSession, client: IBSngClient, payment: Payment) -> str` (`app/services/payments/service.py`). Task 4's webhook route calls `activate_finished_payment` and a module-level `CryptoProvider()` instance's `verify_webhook`; Task 5's bot handlers call `create_crypto_payment` with this exact keyword signature.

- [ ] **Step 1: Write the failing test for `WebhookEvent`/`PaymentProvider`**

Create `tests/functional/test_payments_service.py`:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


def test_webhook_event_holds_expected_fields() -> None:
    from app.services.payments.base import WebhookEvent

    event = WebhookEvent(provider_payment_id="np-1", order_id="42", raw_status="finished", paid_amount=Decimal("5"))
    assert event.provider_payment_id == "np-1"
    assert event.order_id == "42"
    assert event.raw_status == "finished"
    assert event.paid_amount == Decimal("5")


def test_payment_provider_is_abstract() -> None:
    from app.services.payments.base import PaymentProvider

    with pytest.raises(TypeError):
        PaymentProvider()  # type: ignore[abstract]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_payments_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.payments.base'`

- [ ] **Step 3: Create `app/services/payments/base.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class WebhookEvent:
    provider_payment_id: str
    order_id: str
    raw_status: str
    paid_amount: Decimal | None  # in the invoice's pay_currency, not USD - see Payment.paid_amount


class PaymentProvider(ABC):
    """Exactly two methods, deliberately - a provider's job is talking to
    its gateway (create an invoice, verify a signature), never Homeland
    domain logic like which IBSng call to make. See
    docs/superpowers/specs/2026-09-16-crypto-payment-design.md §4 for why
    this differs from the parent spec's original sketch."""

    @abstractmethod
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        """Returns (url to hand the buyer, provider's own payment id)."""

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        """Verifies signature, parses the callback. None if invalid."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/functional/test_payments_service.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write the failing tests for `CryptoProvider`**

Append to `tests/functional/test_payments_service.py`:

```python
@pytest.mark.asyncio
async def test_crypto_provider_create_invoice_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.payments import nowpayments
    from app.services.payments.crypto_provider import CryptoProvider

    async def _fake_create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]:
        assert order_id == "7"
        assert amount == Decimal("9.00")
        assert description == "Homeland: 2 Months"
        return "https://nowpayments.io/payment/xyz", "np-777"

    monkeypatch.setattr(nowpayments, "create_invoice", _fake_create_invoice)

    provider = CryptoProvider()
    url, payment_id = await provider.create_invoice(order_id="7", amount_usd=Decimal("9.00"), description="Homeland: 2 Months")
    assert url == "https://nowpayments.io/payment/xyz"
    assert payment_id == "np-777"


def test_crypto_provider_verify_webhook_returns_event_on_valid_signature() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings
    from app.services.payments.crypto_provider import CryptoProvider

    payload = {"order_id": "42", "payment_id": "np-1", "payment_status": "finished", "actually_paid": "5.0"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = get_settings().nowpayments_ipn_secret
    signature = hmac_module.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()

    event = CryptoProvider().verify_webhook(raw_body, signature)
    assert event is not None
    assert event.order_id == "42"
    assert event.provider_payment_id == "np-1"
    assert event.raw_status == "finished"
    assert event.paid_amount == Decimal("5.0")


def test_crypto_provider_verify_webhook_returns_none_on_invalid_signature() -> None:
    from app.services.payments.crypto_provider import CryptoProvider

    event = CryptoProvider().verify_webhook(b'{"order_id": "1"}', "not-a-valid-signature")
    assert event is None


def test_crypto_provider_verify_webhook_returns_none_when_order_id_missing() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings
    from app.services.payments.crypto_provider import CryptoProvider

    payload = {"payment_id": "np-1", "payment_status": "finished"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = get_settings().nowpayments_ipn_secret
    signature = hmac_module.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()

    assert CryptoProvider().verify_webhook(raw_body, signature) is None


def test_crypto_provider_verify_webhook_handles_missing_actually_paid() -> None:
    import hashlib
    import hmac as hmac_module
    import json as json_module

    from app.config import get_settings
    from app.services.payments.crypto_provider import CryptoProvider

    payload = {"order_id": "42", "payment_id": "np-1", "payment_status": "waiting"}
    raw_body = json_module.dumps(payload).encode()
    canonical = json_module.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = get_settings().nowpayments_ipn_secret
    signature = hmac_module.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()

    event = CryptoProvider().verify_webhook(raw_body, signature)
    assert event is not None
    assert event.paid_amount is None
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/functional/test_payments_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.payments.crypto_provider'`

- [ ] **Step 7: Create `app/services/payments/crypto_provider.py`**

```python
from __future__ import annotations

import json
from decimal import Decimal

from app.config import get_settings
from app.services.payments import nowpayments
from app.services.payments.base import PaymentProvider, WebhookEvent


class CryptoProvider(PaymentProvider):
    async def create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return await nowpayments.create_invoice(order_id=order_id, amount=amount_usd, description=description)

    def verify_webhook(self, raw_body: bytes, signature: str) -> WebhookEvent | None:
        settings = get_settings()
        if not nowpayments.verify_ipn_signature(raw_body, signature, settings.nowpayments_ipn_secret):
            return None
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            return None
        order_id = data.get("order_id")
        payment_id = data.get("payment_id") or data.get("id")
        if not order_id or not payment_id:
            return None
        paid = data.get("actually_paid")
        return WebhookEvent(
            provider_payment_id=str(payment_id),
            order_id=str(order_id),
            raw_status=data.get("payment_status", ""),
            paid_amount=Decimal(str(paid)) if paid is not None else None,
        )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/functional/test_payments_service.py -v`
Expected: PASS (7 tests)

- [ ] **Step 9: Commit**

```bash
git add app/services/payments/base.py app/services/payments/crypto_provider.py tests/functional/test_payments_service.py
git commit -m "feat: add PaymentProvider abstraction and CryptoProvider"
```

- [ ] **Step 10: Write the failing tests for `create_crypto_payment`**

Append to `tests/functional/test_payments_service.py`:

```python
@pytest.mark.asyncio
async def test_create_crypto_payment_purchase_creates_pending_row_with_invoice(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/abc", "np-999"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(
            session, telegram_id=950, purpose="purchase", plan=plan, vpn_user=None,
        )

    assert payment.id is not None
    assert payment.purpose == "purchase"
    assert payment.vpn_user_id is None
    assert payment.plan_id == plan_id
    assert payment.group_name == "1M-1U-Iran-10G"
    assert payment.data_cap_mb == 10240
    assert payment.amount_usd == Decimal("5.00")
    assert payment.original_amount_usd is None
    assert payment.invoice_url == "https://nowpayments.io/payment/abc"
    assert payment.provider_payment_id == "np-999"
    assert payment.status == "pending"
    assert payment.ibsng_username is not None
    assert payment.ibsng_password is not None


@pytest.mark.asyncio
async def test_create_crypto_payment_renew_targets_existing_service(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/renew", "np-1000"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    stream_plan_id = _plan_id(seeded_catalog, category="stream", name="1 Month")
    username, password = generate_vpn_credentials()
    async with async_session_maker() as session, IBSngClient() as client:
        existing = await create_vpn_user(
            session, client, telegram_id=951, username=username, password=password,
            group_name="1M-1U-Iran-10G", data_cap_mb=10240, plan_id=scroll_plan_id,
        )

    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        new_plan = await get_plan(session, stream_plan_id)
        payment = await create_crypto_payment(
            session, telegram_id=951, purpose="renew", plan=new_plan, vpn_user=existing,
        )

    assert payment.purpose == "renew"
    assert payment.vpn_user_id == existing.id
    assert payment.plan_id == stream_plan_id
    assert payment.ibsng_username is None
    assert payment.ibsng_password is None


@pytest.mark.asyncio
async def test_create_crypto_payment_applies_auto_discount(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.discounts import create_discount_code
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/disc", "np-1001"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        discount = await create_discount_code(
            session, code="TENOFF", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True,
        )

    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(
            session, telegram_id=952, purpose="purchase", plan=plan, vpn_user=None,
        )

    assert payment.amount_usd == Decimal("4.50")
    assert payment.original_amount_usd == Decimal("5.00")
    assert payment.discount_code_id == discount.id
```

- [ ] **Step 11: Run tests to verify they fail**

Run: `pytest tests/functional/test_payments_service.py -v -k create_crypto_payment`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.payments.service'`

- [ ] **Step 12: Create `app/services/payments/service.py` (part 1: `create_crypto_payment`)**

```python
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discount_code import DiscountCode
from app.db.models.payment import Payment
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.services.discounts import discount_price, find_best_auto_discount, increment_discount_usage
from app.services.ibsng.client import IBSngClient
from app.services.payments.base import PaymentProvider
from app.services.payments.crypto_provider import CryptoProvider
from app.services.vpn_users import create_vpn_user, generate_vpn_credentials, renew_and_change_group

_provider: PaymentProvider = CryptoProvider()


async def create_crypto_payment(
    session: AsyncSession,
    *,
    telegram_id: int,
    purpose: str,  # "purchase" | "renew"
    plan: Plan,
    vpn_user: VPNUser | None,  # required for purpose="renew", None for "purchase"
) -> Payment:
    discount: DiscountCode | None = await find_best_auto_discount(session, plan.id)
    amount = discount_price(plan.price_usd, discount.percent) if discount is not None else plan.price_usd

    payment = Payment(
        telegram_id=telegram_id,
        purpose=purpose,
        vpn_user_id=vpn_user.id if vpn_user is not None else None,
        plan_id=plan.id,
        discount_code_id=discount.id if discount is not None else None,
        group_name=plan.group_name,
        data_cap_mb=plan.data_cap_mb,
        amount_usd=amount,
        original_amount_usd=plan.price_usd if discount is not None else None,
    )
    if purpose == "purchase":
        payment.ibsng_username, payment.ibsng_password = generate_vpn_credentials()

    # Committed BEFORE calling the provider, deliberately - NOWPayments'
    # order_id must be a real, permanent local id, which only exists
    # once this row is committed. If create_invoice then fails, this row
    # is left behind as an orphaned "pending, no invoice_url" Payment -
    # accepted as a harmless stale row, same as any other abandoned
    # checkout, rather than risk order_id pointing at a row that later
    # vanished.
    session.add(payment)
    await session.commit()
    await session.refresh(payment)

    invoice_url, provider_payment_id = await _provider.create_invoice(
        order_id=str(payment.id), amount_usd=amount, description=f"Homeland: {plan.name}"
    )
    payment.invoice_url = invoice_url
    payment.provider_payment_id = provider_payment_id
    await session.commit()
    await session.refresh(payment)
    return payment
```

- [ ] **Step 13: Run tests to verify they pass**

Run: `pytest tests/functional/test_payments_service.py -v -k create_crypto_payment`
Expected: PASS (3 tests)

- [ ] **Step 14: Commit**

```bash
git add app/services/payments/service.py tests/functional/test_payments_service.py
git commit -m "feat: add create_crypto_payment"
```

- [ ] **Step 15: Write the failing tests for `activate_finished_payment`**

Append to `tests/functional/test_payments_service.py`:

```python
@pytest.mark.asyncio
async def test_activate_finished_payment_purchase_creates_vpn_user(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.session import async_session_maker as make_session
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import activate_finished_payment, create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/act", "np-2000"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with make_session() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=960, purpose="purchase", plan=plan, vpn_user=None)

    async with make_session() as session, IBSngClient() as client:
        from sqlalchemy import select

        from app.db.models.payment import Payment

        payment = await session.get(Payment, payment.id)
        username = await activate_finished_payment(session, client, payment)
        await session.commit()

        from app.db.models.vpn_user import VPNUser

        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 960))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ibsng_username == username
    assert payment.vpn_user_id == rows[0].id


@pytest.mark.asyncio
async def test_activate_finished_payment_renew_updates_existing_service(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.session import async_session_maker as make_session
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import activate_finished_payment, create_crypto_payment
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/renew2", "np-2001"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    scroll_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    stream_id = _plan_id(seeded_catalog, category="stream", name="1 Month")
    username, password = generate_vpn_credentials()
    async with make_session() as session, IBSngClient() as client:
        existing = await create_vpn_user(
            session, client, telegram_id=961, username=username, password=password,
            group_name="1M-1U-Iran-10G", data_cap_mb=10240, plan_id=scroll_id,
        )

    async with make_session() as session:
        from app.services.catalog import get_plan

        new_plan = await get_plan(session, stream_id)
        payment = await create_crypto_payment(session, telegram_id=961, purpose="renew", plan=new_plan, vpn_user=existing)

    async with make_session() as session, IBSngClient() as client:
        from app.db.models.payment import Payment

        payment = await session.get(Payment, payment.id)
        returned_username = await activate_finished_payment(session, client, payment)
        await session.commit()

        from app.db.models.vpn_user import VPNUser

        refreshed = await session.get(VPNUser, existing.id)

    assert returned_username == existing.ibsng_username
    assert refreshed.ibsng_group == "1M-1U-Iran-30G"
    assert refreshed.plan_id == stream_id


@pytest.mark.asyncio
async def test_activate_finished_payment_increments_discount_usage(
    seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.session import async_session_maker as make_session
    from app.services.discounts import create_discount_code, get_discount_code
    from app.services.ibsng.client import IBSngClient
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import activate_finished_payment, create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/disc2", "np-2002"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with make_session() as session:
        discount = await create_discount_code(
            session, code="ACT10", percent=Decimal("10"), usage_limit=None, plan_ids=[plan_id], is_public=True,
        )

    async with make_session() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=962, purpose="purchase", plan=plan, vpn_user=None)

    async with make_session() as session, IBSngClient() as client:
        from app.db.models.payment import Payment

        payment = await session.get(Payment, payment.id)
        await activate_finished_payment(session, client, payment)
        await session.commit()

    async with make_session() as session:
        refreshed_discount = await get_discount_code(session, discount.id)
    assert refreshed_discount.used_count == 1
```

- [ ] **Step 16: Run tests to verify they fail**

Run: `pytest tests/functional/test_payments_service.py -v -k activate_finished_payment`
Expected: FAIL with `ImportError: cannot import name 'activate_finished_payment'`

- [ ] **Step 17: Add `activate_finished_payment` to `app/services/payments/service.py`**

Append to the end of `app/services/payments/service.py`:

```python
async def activate_finished_payment(session: AsyncSession, client: IBSngClient, payment: Payment) -> str:
    """Only called once, guarded by the webhook route's idempotency check
    (payment.status == "pending") before this runs. Returns the
    username to show the buyer - either newly created or the existing
    renewed one."""
    if payment.purpose == "purchase":
        vpn_user = await create_vpn_user(
            session, client,
            telegram_id=payment.telegram_id,
            username=payment.ibsng_username,
            password=payment.ibsng_password,
            group_name=payment.group_name,
            data_cap_mb=payment.data_cap_mb,
            plan_id=payment.plan_id,
        )
        payment.vpn_user_id = vpn_user.id
        username = vpn_user.ibsng_username
    else:
        vpn_user = await session.get(VPNUser, payment.vpn_user_id)
        await renew_and_change_group(
            session, client,
            username=vpn_user.ibsng_username,
            new_group_name=payment.group_name,
            new_plan_id=payment.plan_id,
            new_data_cap_mb=payment.data_cap_mb,
        )
        username = vpn_user.ibsng_username

    if payment.discount_code_id is not None:
        await increment_discount_usage(session, payment.discount_code_id)

    return username
```

- [ ] **Step 18: Run tests to verify they pass**

Run: `pytest tests/functional/test_payments_service.py -v`
Expected: PASS (13 tests total in the file)

- [ ] **Step 19: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green.

- [ ] **Step 20: Commit**

```bash
git add app/services/payments/service.py tests/functional/test_payments_service.py
git commit -m "feat: add activate_finished_payment"
```

---

## Task 4: Webhook server and process wiring

**Files:**
- Create: `app/webhook.py`
- Modify: `app/main.py`
- Modify: `docker-compose.yml`
- Test: `tests/functional/test_webhook.py`

**Interfaces:**
- Consumes: `Payment`, `PaymentStatusEvent` (Task 1); `CryptoProvider` (Task 3, `app/services/payments/crypto_provider.py`); `activate_finished_payment` (Task 3, `app/services/payments/service.py`); `VPNUsernameTakenError` (existing, `app/services/vpn_users.py`); `IBSngError` (existing, `app/services/ibsng/exceptions.py`).
- Produces: `def create_webhook_app(bot: Bot) -> web.Application` (`app/webhook.py`) — consumed by `app/main.py`'s `main()` function. No later task consumes anything else from this file.

- [ ] **Step 1: Write the failing test for signature rejection**

Create `tests/functional/test_webhook.py`:

```python
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import get_settings
from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


def _sign(payload: dict[str, Any], secret: str | None = None) -> tuple[bytes, str]:
    secret = secret if secret is not None else get_settings().nowpayments_ipn_secret
    raw_body = json.dumps(payload).encode()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha512).hexdigest()
    return raw_body, signature


async def _make_client(bot: Any) -> TestClient:
    from app.webhook import create_webhook_app

    app = create_webhook_app(bot)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


def _plan_id(seeded_catalog: dict, *, category: str, name: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category and p["name"] == name)


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, _ = _sign({"order_id": "1", "payment_status": "finished"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": "wrong"})
        assert response.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_ignores_unknown_order_id(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({"order_id": "999999", "payment_status": "finished", "payment_id": "np-x"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_ignores_out_of_int32_range_order_id(bot: Any) -> None:
    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({"order_id": "99999999999", "payment_status": "finished", "payment_id": "np-x"})
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_webhook.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.webhook'`

- [ ] **Step 3: Create `app/webhook.py`**

```python
from __future__ import annotations

import datetime as dt
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

from app.db.models.payment import Payment
from app.db.models.payment_status_event import PaymentStatusEvent
from app.db.session import async_session_maker
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError
from app.services.payments.crypto_provider import CryptoProvider
from app.services.payments.service import activate_finished_payment
from app.services.vpn_users import VPNUsernameTakenError

logger = logging.getLogger(__name__)

_provider = CryptoProvider()

_FINAL_STATUSES = {
    "finished": "paid",
    "partially_paid": "partially_paid",
    "failed": "failed",
    "expired": "failed",
    "refunded": "refunded",
}
# waiting / confirming / confirmed / sending are progress states - logged
# via PaymentStatusEvent but never change Payment.status or notify the user.

_MAX_POSTGRES_INT = 2**31 - 1


def create_webhook_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/webhooks/crypto", _handle_crypto_ipn)
    return app


async def _handle_crypto_ipn(request: web.Request) -> web.Response:
    raw_body = await request.read()
    signature = request.headers.get("x-nowpayments-sig", "")

    event = _provider.verify_webhook(raw_body, signature)
    if event is None:
        logger.warning("Crypto IPN signature/payload invalid")
        return web.Response(status=401, text="invalid signature")

    bot: Bot = request.app["bot"]

    # int32-range guard: Payment.id is a PostgreSQL `integer` column, and
    # a numerically valid but out-of-range order_id would otherwise pass
    # .isdigit() only to crash session.get() with an unhandled
    # asyncpg.DataError - the same class of bug the Renew Service
    # feature's final review found and fixed for callback_data ids.
    # order_id is just as attacker-reachable here: NOWPayments echoes
    # back whatever order_id was sent, but nothing stops a malicious
    # actor from POSTing directly to this public endpoint with a
    # crafted body.
    order_id_value: int | None = None
    if event.order_id.isdigit() and 0 < int(event.order_id) <= _MAX_POSTGRES_INT:
        order_id_value = int(event.order_id)

    async with async_session_maker() as session:
        payment = await session.get(Payment, order_id_value) if order_id_value is not None else None
        if payment is None:
            return web.Response(status=200, text="ignored")

        session.add(PaymentStatusEvent(
            payment_id=payment.id, raw_status=event.raw_status, paid_amount=event.paid_amount,
        ))
        await session.commit()

        if event.raw_status not in _FINAL_STATUSES:
            return web.Response(status=200, text="ok")  # progress state, nothing to do

        # Idempotency guard: a Payment only leaves "pending" once, right
        # here. A replayed/duplicate IPN for an already-resolved payment
        # is a no-op.
        if payment.status != "pending":
            return web.Response(status=200, text="ignored")

        new_status = _FINAL_STATUSES[event.raw_status]

        if new_status == "paid":
            async with IBSngClient() as client:
                try:
                    username = await activate_finished_payment(session, client, payment)
                except VPNUsernameTakenError:
                    logger.error("Payment %s: pre-generated username collided", payment.id)
                    await bot.send_message(
                        payment.telegram_id,
                        "⚠️ Your payment was received, but we hit a technical issue activating your "
                        "service. Please contact support with your payment date and amount.",
                    )
                    return web.Response(status=200, text="ok")
                except IBSngError as exc:
                    logger.error("Payment %s: IBSng error during activation: %s", payment.id, exc)
                    return web.Response(status=500, text="ibsng error")  # lets NOWPayments retry the IPN

            payment.status = "paid"
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            action = "renewed" if payment.purpose == "renew" else "activated"
            await bot.send_message(
                payment.telegram_id,
                f"🎉 Payment confirmed! Your service (<code>{username}</code>) has been {action}.",
            )

        elif new_status == "partially_paid":
            payment.status = "partially_paid"
            payment.paid_amount = event.paid_amount
            await session.commit()
            # Deliberately no dollar shortfall figure here: actually_paid
            # (event.paid_amount) is in the invoice's pay_currency (e.g.
            # USDT units), not USD, and computing a USD shortfall
            # accurately needs the invoice's pay_currency/pay_amount
            # conversion ratio, which this design doesn't track. The
            # linked payment page itself shows the exact remaining
            # balance in the correct currency.
            await bot.send_message(
                payment.telegram_id,
                "⚠️ We received a partial payment — it wasn't quite enough to complete your order, "
                "so your service hasn't been activated yet. Tap below to finish paying the remaining "
                "balance; the page will show exactly how much is left.",
                reply_markup=_topup_keyboard(payment),
            )

        else:  # "failed" or "refunded"
            payment.status = new_status
            payment.resolved_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            if new_status == "failed":
                await bot.send_message(
                    payment.telegram_id,
                    "❌ This payment did not complete. You can start over any time from "
                    "Buy Subscription or Renew Service.",
                )
            # "refunded": recorded, no user-facing message defined for v1.

    return web.Response(status=200, text="ok")


def _topup_keyboard(payment: Payment) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payment.invoice_url:
        builder.button(text="💰 Finish Payment", url=payment.invoice_url)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/functional/test_webhook.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the failing test for the "finished" happy path**

Append to `tests/functional/test_webhook.py`:

```python
@pytest.mark.asyncio
async def test_webhook_finished_activates_purchase_and_notifies_user(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh1", "np-wh-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=970, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-1", "payment_status": "finished",
            "actually_paid": "5.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from app.db.models.payment import Payment
        from app.db.models.vpn_user import VPNUser
        from sqlalchemy import select

        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "paid"
        assert refreshed.vpn_user_id is not None

        vpn_user = await session.get(VPNUser, refreshed.vpn_user_id)
        assert vpn_user.telegram_id == 970

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "confirmed" in sent[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_webhook_duplicate_finished_delivery_is_idempotent(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh2", "np-wh-2"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=971, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-2", "payment_status": "finished",
            "actually_paid": "5.0",
        })
        for _ in range(2):
            response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
            assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.vpn_user import VPNUser

        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 971))).scalars().all()
    assert len(rows) == 1  # NOT two - the second IPN delivery was a no-op

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1  # only the first delivery notified the user
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/functional/test_webhook.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Write the failing test for "partially_paid"**

Append to `tests/functional/test_webhook.py`:

```python
@pytest.mark.asyncio
async def test_webhook_partially_paid_does_not_activate_and_shows_no_dollar_figure(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh3", "np-wh-3"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=972, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-3", "payment_status": "partially_paid",
            "actually_paid": "3.0",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.payment import Payment
        from app.db.models.vpn_user import VPNUser

        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "partially_paid"
        assert refreshed.paid_amount == Decimal("3.0")

        rows = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 972))).scalars().all()
    assert rows == []  # never activated

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    text = sent[0][1]["text"]
    assert "$" not in text  # never fabricates a dollar shortfall from crypto units
    buttons = [b["text"] for row in sent[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "💰 Finish Payment" in buttons


@pytest.mark.asyncio
async def test_webhook_failed_marks_payment_failed(
    bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.crypto_provider import CryptoProvider
    from app.services.payments.service import create_crypto_payment

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/wh4", "np-wh-4"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")
    async with async_session_maker() as session:
        from app.services.catalog import get_plan

        plan = await get_plan(session, plan_id)
        payment = await create_crypto_payment(session, telegram_id=973, purpose="purchase", plan=plan, vpn_user=None)

    client = await _make_client(bot)
    try:
        raw_body, signature = _sign({
            "order_id": str(payment.id), "payment_id": "np-wh-4", "payment_status": "expired",
        })
        response = await client.post("/webhooks/crypto", data=raw_body, headers={"x-nowpayments-sig": signature})
        assert response.status == 200
    finally:
        await client.close()

    async with async_session_maker() as session:
        from app.db.models.payment import Payment

        refreshed = await session.get(Payment, payment.id)
        assert refreshed.status == "failed"

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) == 1
    assert "did not complete" in sent[0][1]["text"].lower()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/functional/test_webhook.py -v`
Expected: PASS (7 tests)

- [ ] **Step 9: Wire the webhook server into `app/main.py`**

Change:

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
```

to:

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from aiohttp import web

from app.webhook import create_webhook_app
```

(Note: this second import block goes alongside the existing `from app.bot.error_handlers import handle_pool_timeout` line and other `app.*` imports further down in the file - keep those import groupings as they already are, just add these two new lines to the appropriate existing groups: `from aiohttp import web` with the third-party imports, `from app.webhook import create_webhook_app` with the `app.*` imports.)

Then change:

```python
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
```

to:

```python
    await bot.delete_webhook(drop_pending_updates=True)

    runner = web.AppRunner(create_webhook_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()
    logger.info("Webhook server listening on :%s", settings.webhook_port)

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
```

- [ ] **Step 10: Expose the webhook port in `docker-compose.yml`**

In `docker-compose.yml`, the `bot` service currently has no `ports:` entry. Add one:

```yaml
  bot:
    build: .
    env_file: .env
    ports:
      - "${WEBHOOK_PORT:-8090}:${WEBHOOK_PORT:-8090}"
    networks:
      - default
```

(Insert `ports:` right after `env_file: .env`, keeping every other line in the `bot` service exactly as it already is.)

- [ ] **Step 11: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green.

- [ ] **Step 12: Commit**

```bash
git add app/webhook.py app/main.py docker-compose.yml tests/functional/test_webhook.py
git commit -m "feat: add crypto IPN webhook server and process wiring"
```

---

## Task 5: Bot flow — Buy Subscription and Renew Service confirm screens

**Files:**
- Modify: `app/bot/keyboards/buy.py`
- Modify: `app/bot/handlers/buy.py`
- Modify: `app/bot/keyboards/renew.py`
- Modify: `app/bot/handlers/renew.py`
- Test: `tests/functional/test_buy_flow.py`
- Test: `tests/functional/test_renew_flow.py`

**Interfaces:**
- Consumes: `create_crypto_payment(session, *, telegram_id, purpose, plan, vpn_user)` (Task 3, exact keyword signature); `NowPaymentsError`, `PaymentProviderNotConfiguredError` (Task 2, `app/services/payments/nowpayments.py`).
- Produces: `payment_link_keyboard(invoice_url: str) -> InlineKeyboardMarkup` (`app/bot/keyboards/buy.py`) — imported by `renew.py` as well. No later task consumes anything from this task.

- [ ] **Step 1: Write the failing tests for Buy's crypto payment flow**

Append to `tests/functional/test_buy_flow.py`:

```python
@pytest.mark.asyncio
async def test_buy_confirm_creates_payment_and_shows_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.services.payments.crypto_provider import CryptoProvider

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/buytest", "np-buy-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "complete your payment" in edited[0][1]["text"].lower()
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    link_button = next(b for b in all_buttons if b["text"] == "🔗 Open Payment Page")
    assert link_button["url"] == "https://nowpayments.io/payment/buytest"

    from app.db.session import async_session_maker

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.payment import Payment

        rows = (await session.execute(select(Payment).where(Payment.telegram_id == 999))).scalars().all()
    assert len(rows) == 1
    assert rows[0].purpose == "purchase"
    assert rows[0].plan_id == plan_id
    assert rows[0].provider_payment_id == "np-buy-1"


@pytest.mark.asyncio
async def test_buy_confirm_shows_coming_soon_when_provider_not_configured(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_buy_confirm_shows_unavailable_message_on_api_error(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments import nowpayments

    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async def _boom(*, order_id: str, amount, description: str):
        raise nowpayments.NowPaymentsError("simulated failure")

    monkeypatch.setattr(nowpayments, "create_invoice", _boom)
    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:confirm:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "couldn't reach the payment provider" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_buy_price_summary_shows_crypto_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
) -> None:
    plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(999, f"buy:plan:{plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "₿ Pay with Crypto" in buttons
    assert "✅ Buy" not in buttons
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/functional/test_buy_flow.py -v -k "crypto or provider_not_configured or unavailable_message or crypto_button"`
Expected: FAIL — the button still says "✅ Buy" and `buy_confirm_cb` still shows `_COMING_SOON_TEXT` unconditionally, so the payment-creation assertions fail.

- [ ] **Step 3: Update `app/bot/keyboards/buy.py`**

Change:

```python
def buy_price_summary_keyboard(plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Buy", callback_data=f"buy:confirm:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"buy:category:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

to:

```python
def buy_price_summary_keyboard(plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="₿ Pay with Crypto", callback_data=f"buy:confirm:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"buy:category:{category}")
    builder.adjust(1)
    return builder.as_markup()


def payment_link_keyboard(invoice_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Open Payment Page", url=invoice_url)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Update `app/bot/handlers/buy.py`**

Change the imports at the top of `app/bot/handlers/buy.py` — from:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import buy_category_keyboard, buy_plan_keyboard, buy_price_summary_keyboard
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, format_data_cap, format_price_usd, get_plan, list_plans
from app.services.discounts import discount_price, find_best_auto_discount
```

to:

```python
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import (
    buy_category_keyboard,
    buy_plan_keyboard,
    buy_price_summary_keyboard,
    payment_link_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, format_data_cap, format_price_usd, get_plan, list_plans
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.payments.nowpayments import NowPaymentsError, PaymentProviderNotConfiguredError
from app.services.payments.service import create_crypto_payment

logger = logging.getLogger(__name__)
```

Add these two constants near `_COMING_SOON_TEXT` (keep `_COMING_SOON_TEXT` itself exactly as it is — it becomes the fallback for an unconfigured provider):

```python
_PAYMENT_LINK_TEXT = (
    "💳 <b>Complete your payment</b>\n\n"
    "Tap below to open the payment page — you'll be able to choose your "
    "coin and network there. We'll confirm automatically once payment is "
    "received; no need to come back and check."
)
_PAYMENT_UNAVAILABLE_TEXT = (
    "⚠️ We couldn't reach the payment provider right now. Please try again "
    "in a few minutes, or contact support if this keeps happening."
)
```

Change `buy_confirm_cb` — from:

```python
@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
    if not _is_buyable(plan):
        if callback.message is not None:
            await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
        await callback.answer()
        return
    if callback.message is not None:
        await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
    await callback.answer()
```

to:

```python
@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery) -> None:
    plan_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="purchase", plan=plan, vpn_user=None,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error("NOWPayments invoice creation failed for plan %s", plan_id)
            if callback.message is not None:
                await callback.message.edit_text(_PAYMENT_UNAVAILABLE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

    if callback.message is not None:
        await callback.message.edit_text(_PAYMENT_LINK_TEXT, reply_markup=payment_link_keyboard(payment.invoice_url))
    await callback.answer()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/functional/test_buy_flow.py -v`
Expected: PASS (all tests in the file, including the new ones and every pre-existing one — check `test_buy_confirm_rejects_trial_plan_id` and `test_buy_confirm_not_found_shows_gone_message` still pass unchanged, since those hit the `_is_buyable`/not-found branches before any payment logic runs).

- [ ] **Step 6: Commit**

```bash
git add app/bot/keyboards/buy.py app/bot/handlers/buy.py tests/functional/test_buy_flow.py
git commit -m "feat: wire Buy Subscription's confirm screen to real crypto payments"
```

- [ ] **Step 7: Write the failing tests for Renew's crypto payment flow**

Append to `tests/functional/test_renew_flow.py`:

```python
@pytest.mark.asyncio
async def test_renew_confirm_creates_payment_and_shows_link(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.services.payments.crypto_provider import CryptoProvider

    telegram_id = 840
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    async def _fake_create_invoice(self: CryptoProvider, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]:
        return "https://nowpayments.io/payment/renewtest", "np-renew-1"

    monkeypatch.setattr(CryptoProvider, "create_invoice", _fake_create_invoice)
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "complete your payment" in edited[0][1]["text"].lower()
    all_buttons = [b for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    link_button = next(b for b in all_buttons if b["text"] == "🔗 Open Payment Page")
    assert link_button["url"] == "https://nowpayments.io/payment/renewtest"

    async with async_session_maker() as session:
        from sqlalchemy import select

        from app.db.models.payment import Payment

        rows = (await session.execute(select(Payment).where(Payment.telegram_id == telegram_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].purpose == "renew"
    assert rows[0].vpn_user_id == service.id
    assert rows[0].plan_id == scroll_plan_id


@pytest.mark.asyncio
async def test_renew_confirm_shows_coming_soon_when_provider_not_configured(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    telegram_id = 841
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    monkeypatch.setattr(get_settings(), "nowpayments_api_key", "")
    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:confirm:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "coming soon" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_renew_price_summary_shows_crypto_button(
    dispatcher: Any, bot: Any, fake_session: FakeBotSession, seeded_catalog: dict,
) -> None:
    telegram_id = 842
    service = await _create_service(seeded_catalog, telegram_id=telegram_id, category="stream", name="1 Month")
    scroll_plan_id = _plan_id(seeded_catalog, category="scroll", name="1 Month")

    await dispatcher.feed_update(bot, make_callback_update(telegram_id, f"renew:plan:{service.id}:{scroll_plan_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert "₿ Pay with Crypto" in buttons
    assert "✅ Renew" not in buttons
```

(`_create_service` and `_plan_id` are the existing helpers already defined at the top of `tests/functional/test_renew_flow.py` — reuse them as-is, do not redefine.)

- [ ] **Step 8: Run tests to verify they fail**

Run: `pytest tests/functional/test_renew_flow.py -v -k "crypto or provider_not_configured"`
Expected: FAIL — same reason as Buy's Step 2.

- [ ] **Step 9: Update `app/bot/keyboards/renew.py`**

Change:

```python
def renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Renew", callback_data=f"renew:confirm:{vpn_user_id}:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"renew:category:{vpn_user_id}:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

to:

```python
def renew_price_summary_keyboard(vpn_user_id: int, plan_id: int, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="₿ Pay with Crypto", callback_data=f"renew:confirm:{vpn_user_id}:{plan_id}", style="success")
    builder.button(text="⬅️ Back", callback_data=f"renew:category:{vpn_user_id}:{category}")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 10: Update `app/bot/handlers/renew.py`**

Change the imports at the top of `app/bot/handlers/renew.py` — from:

```python
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_price_summary_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, format_data_cap, format_price_usd, get_plan, list_plans
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services
```

to:

```python
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import payment_link_keyboard
from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_price_summary_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, format_data_cap, format_price_usd, get_plan, list_plans
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.payments.nowpayments import NowPaymentsError, PaymentProviderNotConfiguredError
from app.services.payments.service import create_crypto_payment
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services

logger = logging.getLogger(__name__)
```

Add these two constants near `_COMING_SOON_TEXT` (keep `_COMING_SOON_TEXT` itself exactly as it is — same fallback role as in `buy.py`):

```python
_PAYMENT_LINK_TEXT = (
    "💳 <b>Complete your payment</b>\n\n"
    "Tap below to open the payment page — you'll be able to choose your "
    "coin and network there. We'll confirm automatically once payment is "
    "received; no need to come back and check."
)
_PAYMENT_UNAVAILABLE_TEXT = (
    "⚠️ We couldn't reach the payment provider right now. Please try again "
    "in a few minutes, or contact support if this keeps happening."
)
```

Change `renew_confirm_cb` — from:

```python
@router.callback_query(F.data.startswith("renew:confirm:"))
async def renew_confirm_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback)
        return

    plan_id = _parse_int(parts[3]) if len(parts) > 3 else None
    if plan_id is None:
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return

        plan = await get_plan(session, plan_id) if _in_postgres_int_range(plan_id) else None
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

    # renew_and_change_group is deliberately never called here - no
    # renewal is executed until a real payment provider exists (spec §7).
    if callback.message is not None:
        await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
    await callback.answer()
```

to:

```python
@router.callback_query(F.data.startswith("renew:confirm:"))
async def renew_confirm_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback)
        return

    plan_id = _parse_int(parts[3]) if len(parts) > 3 else None
    if plan_id is None:
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return

        plan = await get_plan(session, plan_id) if _in_postgres_int_range(plan_id) else None
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="renew", plan=plan, vpn_user=vpn_user,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error("NOWPayments invoice creation failed for vpn_user %s plan %s", vpn_user_id, plan_id)
            if callback.message is not None:
                await callback.message.edit_text(_PAYMENT_UNAVAILABLE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return

    # renew_and_change_group is deliberately never called here - no
    # renewal is executed until the webhook (app/webhook.py) reports the
    # payment as "finished".
    if callback.message is not None:
        await callback.message.edit_text(_PAYMENT_LINK_TEXT, reply_markup=payment_link_keyboard(payment.invoice_url))
    await callback.answer()
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `pytest tests/functional/test_renew_flow.py -v`
Expected: PASS (all tests in the file, including the new ones and every pre-existing one).

- [ ] **Step 12: Run the full test suite**

Run: `make test`
Expected: PASS, full suite green.

- [ ] **Step 13: Commit**

```bash
git add app/bot/keyboards/renew.py app/bot/handlers/renew.py tests/functional/test_renew_flow.py
git commit -m "feat: wire Renew Service's confirm screen to real crypto payments"
```

---

## Self-Review

**1. Spec coverage:**
- §1 (Summary) — Task 5 relabels both buttons and creates real payments; Task 4's webhook only activates on `finished`. Covered.
- §2 (Navigation) — no callback-data namespace changes; confirmed no task adds one. Covered.
- §3 (Data model) — Task 1, verbatim `Payment`/`PaymentStatusEvent` from the spec (with the spec's own two self-corrected type annotations already fixed). Covered.
- §4 (ABC deviation) — Task 3's `PaymentProvider` has exactly two methods, matching the spec's corrected design; a Global Constraint states this explicitly so no implementer re-adds `on_payment_confirmed`. Covered.
- §5 (Config) — Task 1 Step 9, exact rename plus `bot_username`. Covered.
- §6 (NOWPayments client) — Task 2, verbatim. Covered.
- §7 (PaymentProvider/CryptoProvider) — Task 3 Steps 1-9. Covered.
- §8 (Payments service, discount increment) — Task 1 Step 18 (`increment_discount_usage`) + Task 3 Steps 10-20 (`create_crypto_payment`/`activate_finished_payment`), including the commit-before-provider-call ordering rationale from the spec's own self-review fix. Covered.
- §9 (Webhook server, top-up mechanic, int32 guard, currency caveat) — Task 4, verbatim, including the spec's own self-review fixes (the `paid_amount`/currency caveat, the int32 guard, the removed unused `Decimal` import). Covered.
- §10 (Bot flow) — Task 5, both Buy and Renew, including the spec's own self-review fix (the `NowPaymentsError` branch and `_PAYMENT_UNAVAILABLE_TEXT`, not just `PaymentProviderNotConfiguredError`). Covered.
- §11 (Idempotency/error handling summary) — every point restated as a Global Constraint; Task 4's tests directly exercise duplicate-delivery idempotency and out-of-range order_id handling. Covered.
- §12 (Out of scope) — no task builds Stripe, refund automation, a status-check button, pending-row cleanup, or admin payment visibility; confirmed absent from every task's File Structure entry.

**2. Placeholder scan:** No "TBD"/"TODO"/"similar to Task N" patterns — every step's code is complete, transcribed from the spec's own final (self-reviewed) code blocks rather than re-derived, with TDD scaffolding (test-first steps) added around it.

**3. Type consistency:**
- `Payment.paid_amount` (Task 1) / `PaymentStatusEvent.paid_amount` (Task 1) / `WebhookEvent.paid_amount` (Task 3) / `event.paid_amount` usage in `app/webhook.py` (Task 4) — all named `paid_amount` consistently (not `paid_amount_usd`), all `Decimal | None`, all documented as pay_currency units. Verified no stray `_usd` suffix survived into any task's code.
- `create_crypto_payment(session, *, telegram_id: int, purpose: str, plan: Plan, vpn_user: VPNUser | None) -> Payment` — defined once in Task 3 Step 12, called identically (same four keyword arguments, same order) at Task 5's two call sites (`buy_confirm_cb` with `vpn_user=None`, `renew_confirm_cb` with `vpn_user=vpn_user`). No signature drift.
- `activate_finished_payment(session, client, payment) -> str` — defined in Task 3 Step 17, called identically in Task 4's webhook route with the same three positional arguments.
- `PaymentProvider.create_invoice(self, *, order_id: str, amount_usd: Decimal, description: str) -> tuple[str, str]` (Task 3's ABC) matches `CryptoProvider.create_invoice`'s implementation signature exactly, which matches `nowpayments.create_invoice(*, order_id: str, amount: Decimal, description: str) -> tuple[str, str]` (Task 2) modulo the `amount_usd`/`amount` parameter-name difference between the ABC layer and the raw client layer — intentional (the ABC speaks in USD explicitly since a future Stripe provider would too; the raw NOWPayments client's `amount` parameter is always USD in practice since `price_currency` is hardcoded to `"usd"`, so the rename at the provider layer is documentation, not a behavior change). Confirmed both call sites (`CryptoProvider.create_invoice` calling `nowpayments.create_invoice`) pass arguments correctly across the rename.
- `payment_link_keyboard(invoice_url: str) -> InlineKeyboardMarkup` — defined once in Task 5 Step 3 (`app/bot/keyboards/buy.py`), imported and reused as-is by `app/bot/handlers/renew.py` (Task 5 Step 10) rather than redefined — confirmed no duplicate definition exists.
- `_PAYMENT_LINK_TEXT`/`_PAYMENT_UNAVAILABLE_TEXT` are deliberately defined twice (once in `buy.py`, once in `renew.py`, identical text) rather than imported — matches this project's established convention (confirmed against Renew Service's own plan self-review, which gave the same reasoning for `_RENEW_CATEGORIES` vs `_BUY_CATEGORIES`) that each flow router owns its own copies of small text constants. Not a duplication bug.
