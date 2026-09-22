# Financial Management Implementation Plan (Epic Part 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill in Revenue Overview and Payments under Financial, and add performance figures to the discount screens.

**Architecture:** A query-only service returns dataclasses; a new `adm:fin:*` router renders them. Filter and period state travels in callback data, not FSM, so a stale keyboard stays meaningful.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async, pytest in the isolated Docker stack.

**Spec:** `docs/superpowers/specs/2026-09-23-financial-management-design.md`

## Global Constraints

- Admin-facing text stays English and never goes through `t()`.
- Read-only: nothing in this part mutates a payment or a discount.
- Revenue counts `status == "paid"` only, dated by `resolved_at` with `created_at` as the fallback.
- Periods are defined once in `app/services/reporting.py` and reused by Part 4.
- Filter and period state lives in callback data; FSM is used only while a free-text search is being typed.
- Sales and above, inheriting `adm:fin`; a refused tap must say so, since the handler consumes the callback.
- Registered before `admin_fallback`, thin handlers, async only, type hints.
- Run the suite with `make test`, or against the running stack: `docker exec homeland_bot_test-test-runner-1 sh -c 'rm -rf /app/app /app/tests'`, `tar --exclude=.git --exclude=.claude -cf - app tests | docker exec -i homeland_bot_test-test-runner-1 tar -xf - -C /app`, `docker exec homeland_bot_test-db_test-1 psql -U homeland_test -d homeland_test -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`, then `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/ -q`.

---

## File Structure

- **Create** `app/services/reporting.py` — periods plus four query functions.
- **Create** `app/bot/keyboards/financial.py` — period, filter, pagination and detail keyboards.
- **Create** `app/bot/handlers/financial.py` — the `adm:fin:*` router.
- **Modify** `app/bot/handlers/admin.py` — drop the Part 1 placeholder handler.
- **Modify** `app/main.py` — register the router.
- **Modify** `app/bot/handlers/admin_discounts.py`, `app/bot/keyboards/admin_discounts.py` — performance block.
- **Create** `tests/functional/test_reporting_service.py`, `tests/functional/test_financial_screens.py`.

---

## Task 1: The reporting service

**Files:**
- Create: `app/services/reporting.py`
- Test: `tests/functional/test_reporting_service.py`

**Interfaces:**
- Produces: `PERIODS: dict[str, Period]`; `revenue_summary(session, *, period: str) -> RevenueSummary`; `payment_page(session, *, status, provider, telegram_id, page) -> PaymentPage`; `payment_detail(session, payment_id) -> PaymentDetail | None`; `discount_performance(session, discount_code_id) -> DiscountPerformance`; `resolve_user_query(session, raw: str) -> int | None`.

- [ ] **Step 1: Write the failing tests**

`tests/functional/test_reporting_service.py`. Seed payments directly rather than driving the bot, so each figure is unambiguous:

```python
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from app.db.session import async_session_maker


async def _payment(
    *, telegram_id: int, amount: str, status: str, provider: str = "plisio",
    days_ago: int = 0, original: str | None = None, discount_code_id: int | None = None,
    plan_id: int | None = None,
) -> int:
    from app.db.models.payment import Payment

    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    async with async_session_maker() as session:
        payment = Payment(
            telegram_id=telegram_id, purpose="purchase", plan_id=plan_id, group_name="2W-1U-Iran-5G",
            data_cap_mb=5120, amount_usd=Decimal(amount), provider=provider, status=status,
            original_amount_usd=Decimal(original) if original else None,
            discount_code_id=discount_code_id, created_at=now,
            resolved_at=now if status in ("paid", "failed", "refunded") else None,
        )
        session.add(payment)
        await session.commit()
        return payment.id


@pytest.mark.asyncio
async def test_revenue_counts_only_paid_rows(seeded_catalog: dict) -> None:
    """Pending money is not revenue, and failed money never was."""
    from app.services.reporting import revenue_summary

    plan_id = seeded_catalog["plans"][0]["id"]
    await _payment(telegram_id=1, amount="10.00", status="paid", plan_id=plan_id)
    await _payment(telegram_id=2, amount="99.00", status="pending", plan_id=plan_id)
    await _payment(telegram_id=3, amount="99.00", status="failed", plan_id=plan_id)

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period="all")

    assert summary.paid_orders == 1
    assert summary.revenue == Decimal("10.00")
    assert summary.by_status["pending"] == 1
    assert summary.by_status["failed"] == 1


@pytest.mark.asyncio
async def test_period_filtering_excludes_older_rows(seeded_catalog: dict) -> None:
    from app.services.reporting import revenue_summary

    plan_id = seeded_catalog["plans"][0]["id"]
    await _payment(telegram_id=1, amount="10.00", status="paid", days_ago=0, plan_id=plan_id)
    await _payment(telegram_id=2, amount="20.00", status="paid", days_ago=10, plan_id=plan_id)
    await _payment(telegram_id=3, amount="40.00", status="paid", days_ago=45, plan_id=plan_id)

    async with async_session_maker() as session:
        assert (await revenue_summary(session, period="today")).revenue == Decimal("10.00")
        assert (await revenue_summary(session, period="7d")).revenue == Decimal("10.00")
        assert (await revenue_summary(session, period="30d")).revenue == Decimal("30.00")
        assert (await revenue_summary(session, period="all")).revenue == Decimal("70.00")


@pytest.mark.asyncio
async def test_by_provider_reflects_the_data_and_keeps_known_providers(seeded_catalog: dict) -> None:
    """Stripe has never taken a payment; it must still be listed at zero
    rather than vanish, so an admin can see it is idle, not missing."""
    from app.services.reporting import revenue_summary

    plan_id = seeded_catalog["plans"][0]["id"]
    await _payment(telegram_id=1, amount="10.00", status="paid", plan_id=plan_id)

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period="all")

    assert summary.by_provider["plisio"].orders == 1
    assert summary.by_provider["plisio"].revenue == Decimal("10.00")
    assert summary.by_provider["stripe"].orders == 0


@pytest.mark.asyncio
async def test_discounts_given_is_original_minus_charged(seeded_catalog: dict) -> None:
    from app.services.reporting import revenue_summary

    plan_id = seeded_catalog["plans"][0]["id"]
    await _payment(telegram_id=1, amount="8.00", original="10.00", status="paid", plan_id=plan_id)

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period="all")

    assert summary.revenue == Decimal("8.00")
    assert summary.discounts_given == Decimal("2.00")


@pytest.mark.asyncio
async def test_payment_page_filters_and_paginates(seeded_catalog: dict) -> None:
    from app.services.reporting import PAGE_SIZE, payment_page

    plan_id = seeded_catalog["plans"][0]["id"]
    for index in range(PAGE_SIZE + 3):
        await _payment(telegram_id=100 + index, amount="5.00", status="paid", plan_id=plan_id)
    await _payment(telegram_id=999, amount="5.00", status="failed", plan_id=plan_id)

    async with async_session_maker() as session:
        first = await payment_page(session, status=None, provider=None, telegram_id=None, page=0)
        assert len(first.rows) == PAGE_SIZE
        assert first.total == PAGE_SIZE + 4

        failed = await payment_page(session, status="failed", provider=None, telegram_id=None, page=0)
        assert failed.total == 1

        mine = await payment_page(session, status=None, provider=None, telegram_id=100, page=0)
        assert mine.total == 1


@pytest.mark.asyncio
async def test_resolve_user_query_accepts_id_and_username(seeded_catalog: dict) -> None:
    from app.services.bot_users import record_seen
    from app.services.reporting import resolve_user_query

    async with async_session_maker() as session:
        await record_seen(session, 4242, "someone")

    async with async_session_maker() as session:
        assert await resolve_user_query(session, "4242") == 4242
        assert await resolve_user_query(session, "@someone") == 4242
        assert await resolve_user_query(session, "someone") == 4242
        assert await resolve_user_query(session, "nobody") is None


@pytest.mark.asyncio
async def test_discount_performance_counts_only_paid_payments(seeded_catalog: dict) -> None:
    from app.services.discounts import create_discount_code
    from app.services.reporting import discount_performance

    plan_id = seeded_catalog["plans"][0]["id"]
    async with async_session_maker() as session:
        code = await create_discount_code(
            session, code="SUMMER20", percent=Decimal("20"), usage_limit=10, plan_ids=None, is_public=True
        )

    await _payment(telegram_id=1, amount="8.00", original="10.00", status="paid",
                   discount_code_id=code.id, plan_id=plan_id)
    await _payment(telegram_id=2, amount="8.00", original="10.00", status="pending",
                   discount_code_id=code.id, plan_id=plan_id)

    async with async_session_maker() as session:
        performance = await discount_performance(session, code.id)

    assert performance.paid_payments == 1
    assert performance.revenue == Decimal("8.00")
    assert performance.discount_given == Decimal("2.00")
```

Check `create_discount_code`'s real signature before writing that last test and adapt the call.

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_reporting_service.py -q`
Expected: FAIL with `ModuleNotFoundError: app.services.reporting`.

- [ ] **Step 3: Write the service**

`app/services/reporting.py`. Query-only, no aiogram imports, so Part 4 can reuse it:

```python
"""Read-only queries behind the Financial and Reports screens.

No aiogram imports: Part 4's reports reuse these same functions and the
same period definitions, so the two cannot drift apart.

Revenue means `status == "paid"` and nothing else. Pending money has not
arrived and failed money never did, so neither is counted - a report
that flatters itself is worse than no report.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser
from app.db.models.discount_code import DiscountCode
from app.db.models.payment import Payment

PAGE_SIZE = 8

#: Providers always shown, even at zero: an admin needs to see that
#: Stripe is idle rather than wonder whether it is missing.
KNOWN_PROVIDERS = ("plisio", "stripe")


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    days: int | None  # None = all time


PERIODS: dict[str, Period] = {
    "today": Period("today", "Today", 0),
    "7d": Period("7d", "7 days", 7),
    "30d": Period("30d", "30 days", 30),
    "all": Period("all", "All time", None),
}
DEFAULT_PERIOD = "30d"


def period_start(period: str) -> dt.datetime | None:
    """None means "no lower bound". "today" is midnight UTC, not 24
    hours ago, because an admin asking for today means the calendar
    day."""
    spec = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])
    if spec.days is None:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    if spec.days == 0:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - dt.timedelta(days=spec.days)


def _effective_date():  # type: ignore[no-untyped-def]
    """When the money actually landed. resolved_at is set the moment a
    payment reaches a terminal state; created_at covers rows that
    predate it or never resolved."""
    return func.coalesce(Payment.resolved_at, Payment.created_at)


@dataclass
class ProviderTotals:
    orders: int = 0
    revenue: Decimal = Decimal("0.00")


@dataclass
class RevenueSummary:
    period: str
    paid_orders: int
    revenue: Decimal
    discounts_given: Decimal
    by_provider: dict[str, ProviderTotals]
    by_status: dict[str, int]

    @property
    def average_order(self) -> Decimal:
        if not self.paid_orders:
            return Decimal("0.00")
        return (self.revenue / self.paid_orders).quantize(Decimal("0.01"))


async def revenue_summary(session: AsyncSession, *, period: str) -> RevenueSummary:
    start = period_start(period)
    paid = [Payment.status == "paid"]
    if start is not None:
        paid.append(_effective_date() >= start)

    totals = (
        await session.execute(
            select(
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount_usd), 0),
                func.coalesce(
                    func.sum(
                        func.coalesce(Payment.original_amount_usd, Payment.amount_usd) - Payment.amount_usd
                    ),
                    0,
                ),
            ).where(*paid)
        )
    ).one()

    provider_rows = (
        await session.execute(
            select(Payment.provider, func.count(Payment.id), func.coalesce(func.sum(Payment.amount_usd), 0))
            .where(*paid)
            .group_by(Payment.provider)
        )
    ).all()
    by_provider = {name: ProviderTotals() for name in KNOWN_PROVIDERS}
    for provider, orders, revenue in provider_rows:
        by_provider[provider] = ProviderTotals(orders=orders, revenue=Decimal(revenue))

    status_filters = [] if start is None else [_effective_date() >= start]
    status_rows = (
        await session.execute(
            select(Payment.status, func.count(Payment.id)).where(*status_filters).group_by(Payment.status)
        )
    ).all()

    return RevenueSummary(
        period=period,
        paid_orders=totals[0],
        revenue=Decimal(totals[1]),
        discounts_given=Decimal(totals[2]),
        by_provider=by_provider,
        by_status={status: count for status, count in status_rows},
    )
```

Then `payment_page`, `payment_detail`, `resolve_user_query` and
`discount_performance` in the same file:

```python
@dataclass
class PaymentRow:
    id: int
    telegram_id: int
    username: str | None
    amount_usd: Decimal
    status: str
    provider: str
    created_at: dt.datetime


@dataclass
class PaymentPage:
    rows: list[PaymentRow]
    page: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // PAGE_SIZE))


async def payment_page(
    session: AsyncSession, *, status: str | None, provider: str | None, telegram_id: int | None, page: int
) -> PaymentPage:
    filters = []
    if status:
        filters.append(Payment.status == status)
    if provider:
        filters.append(Payment.provider == provider)
    if telegram_id is not None:
        filters.append(Payment.telegram_id == telegram_id)

    total = (await session.execute(select(func.count(Payment.id)).where(*filters))).scalar_one()
    rows = (
        await session.execute(
            select(Payment, BotUser.username)
            .outerjoin(BotUser, BotUser.telegram_id == Payment.telegram_id)
            .where(*filters)
            .order_by(Payment.id.desc())
            .offset(page * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    ).all()
    return PaymentPage(
        rows=[
            PaymentRow(
                id=p.id, telegram_id=p.telegram_id, username=username, amount_usd=p.amount_usd,
                status=p.status, provider=p.provider, created_at=p.created_at,
            )
            for p, username in rows
        ],
        page=page,
        total=total,
    )


async def resolve_user_query(session: AsyncSession, raw: str) -> int | None:
    """Accepts a numeric Telegram id, "@username" or a bare username.
    Returns None when nothing matches, which the caller reports rather
    than silently showing every payment."""
    value = raw.strip().lstrip("@")
    if not value:
        return None
    if value.isdigit():
        return int(value)
    row = (
        await session.execute(
            select(BotUser.telegram_id).where(func.lower(BotUser.username) == value.lower()).limit(1)
        )
    ).scalar_one_or_none()
    return row


@dataclass
class DiscountPerformance:
    used_count: int
    usage_limit: int | None
    paid_payments: int
    revenue: Decimal
    discount_given: Decimal


async def discount_performance(session: AsyncSession, discount_code_id: int) -> DiscountPerformance:
    code = await session.get(DiscountCode, discount_code_id)
    row = (
        await session.execute(
            select(
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount_usd), 0),
                func.coalesce(
                    func.sum(
                        func.coalesce(Payment.original_amount_usd, Payment.amount_usd) - Payment.amount_usd
                    ),
                    0,
                ),
            ).where(Payment.discount_code_id == discount_code_id, Payment.status == "paid")
        )
    ).one()
    return DiscountPerformance(
        used_count=code.used_count if code else 0,
        usage_limit=code.usage_limit if code else None,
        paid_payments=row[0],
        revenue=Decimal(row[1]),
        discount_given=Decimal(row[2]),
    )
```

`payment_detail` returns the `Payment` row plus its plan name and the
buyer's username; model it on `payment_page`'s join.

- [ ] **Step 4: Run and commit**

Run: `docker exec homeland_bot_test-test-runner-1 python -m pytest tests/functional/test_reporting_service.py -q`
Expected: PASS.

```bash
git add app/services/reporting.py tests/functional/test_reporting_service.py
git commit -m "feat: read-only reporting queries for revenue, payments and discounts"
```

---

## Task 2: The screens

**Files:**
- Create: `app/bot/keyboards/financial.py`, `app/bot/handlers/financial.py`
- Modify: `app/bot/handlers/admin.py`, `app/main.py`
- Test: `tests/functional/test_financial_screens.py`

**Interfaces:**
- Callbacks: `adm:fin:revenue[:<period>]`, `adm:fin:payments[:<status>:<provider>:<page>]`, `adm:fin:payments:user` (search prompt), `adm:fin:payment:<id>`.

- [ ] **Step 1: Write the failing tests**

Cover: revenue renders each period and the by-provider block; payments lists and paginates; each filter narrows; the user search accepts a username and reports a miss; a payment detail renders; a support admin is refused each callback. Assert on rendered text and `callback_data`, driving the real dispatcher as the other admin tests do.

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — Part 1's placeholder still answers `adm:fin:revenue`.

- [ ] **Step 3: Build the keyboards and router**

Period row for revenue; status row, provider row, prev/next and a "🔍 Find by user" button for payments; a Back to Financial on both. The router mirrors `admin.py`'s inline gate (`has_level(..., "sales")`, refusing with `NO_PERMISSION_TEXT` since the handler consumes the callback). The free-text search uses one FSM state, cleared on every navigation, following the Block a User prompt.

- [ ] **Step 4: Remove Part 1's placeholder**

Delete `admin_financial_placeholder_cb` and `_FINANCIAL_SOON_TEXT` from `app/bot/handlers/admin.py`, and register `financial.router` in `app/main.py` before `admin_fallback`.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add app tests
git commit -m "feat: revenue overview and payment search screens"
```

---

## Task 3: Discount performance

**Files:**
- Modify: `app/bot/handlers/admin_discounts.py`
- Test: `tests/functional/test_admin_discounts.py`

- [ ] **Step 1: Write the failing test**

A discount with one paid and one pending payment shows used count, revenue and discount given, counting only the paid one.

- [ ] **Step 2: Add the block**

Append the performance lines to the existing detail text via `discount_performance`. No new screen, no new callback.

- [ ] **Step 3: Full suite and commit**

```bash
git add app tests
git commit -m "feat: discount code performance on the detail screen"
```

---

## Task 4: Docs and deploy

- [ ] **Step 1: CLAUDE.md** — record that `app/services/reporting.py` is the single source of revenue definitions and period boundaries, shared with Part 4.
- [ ] **Step 2: Deploy** — push, pull, rebuild, check the log.
- [ ] **Step 3: Verify** — open Financial, check Revenue against the known live data (payment 16 is the only paid order, $3.00), and search Payments by your own Telegram id.

---

## Self-Review

- **Spec coverage:** §3 revenue → Task 1 + Task 2; §4 payments → Task 1's `payment_page`/`payment_detail`/`resolve_user_query` + Task 2; §5 discount performance → Tasks 1 and 3; §2's refund finding → reported via `by_status`, no refund action built; §6 permissions → Task 2 Step 3; §7 shape → Tasks 1–2; §8 tests → each task's first step.
- **Placeholder scan:** Task 2 Steps 1 and 3 describe the screens by their assertions and components rather than quoting every keyboard; the service, which carries all the logic worth getting wrong, is given in full.
- **Type consistency:** `revenue_summary(session, *, period: str) -> RevenueSummary` and `payment_page(session, *, status, provider, telegram_id, page) -> PaymentPage` match their call sites and tests; `PERIODS`/`period_start` are the only definition of a period boundary, which Part 4 imports rather than redefining.
