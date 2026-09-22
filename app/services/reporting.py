"""Read-only queries behind the Financial and Reports screens.

No aiogram imports: the reports screen reuses these same functions and
the same period definitions, so the two cannot drift apart.

Revenue means `status == "paid"` and nothing else. Pending money has not
arrived and failed money never did, so neither is counted - a report
that flatters itself is worse than no report.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser
from app.db.models.discount_code import DiscountCode
from app.db.models.payment import Payment
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser

PAGE_SIZE = 8

#: Providers always shown, even at zero: an admin needs to see that
#: Stripe is idle rather than wonder whether it went missing.
KNOWN_PROVIDERS = ("plisio", "stripe")

#: The only status that counts as money received.
PAID = "paid"


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
    """None means no lower bound. "today" is midnight UTC rather than the
    last 24 hours, because an admin asking for today means the calendar
    day, not a rolling window."""
    spec = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])
    if spec.days is None:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    if spec.days == 0:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - dt.timedelta(days=spec.days)


def _effective_date():  # type: ignore[no-untyped-def]
    """When the money actually landed. resolved_at is set the moment a
    payment reaches a terminal state; created_at covers rows that never
    resolved or predate that column being populated."""
    return func.coalesce(Payment.resolved_at, Payment.created_at)


def _discount_given_sum():  # type: ignore[no-untyped-def]
    """original_amount_usd is only set when a discount applied, so it
    coalesces to the charged amount and contributes zero otherwise."""
    return func.coalesce(
        func.sum(func.coalesce(Payment.original_amount_usd, Payment.amount_usd) - Payment.amount_usd), 0
    )


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
    paid_filters = [Payment.status == PAID]
    if start is not None:
        paid_filters.append(_effective_date() >= start)

    totals = (
        await session.execute(
            select(
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount_usd), 0),
                _discount_given_sum(),
            ).where(*paid_filters)
        )
    ).one()

    provider_rows = (
        await session.execute(
            select(Payment.provider, func.count(Payment.id), func.coalesce(func.sum(Payment.amount_usd), 0))
            .where(*paid_filters)
            .group_by(Payment.provider)
        )
    ).all()
    by_provider: dict[str, ProviderTotals] = {name: ProviderTotals() for name in KNOWN_PROVIDERS}
    for provider, orders, revenue in provider_rows:
        by_provider[provider] = ProviderTotals(orders=orders, revenue=Decimal(str(revenue)))

    status_filters = [] if start is None else [_effective_date() >= start]
    status_rows = (
        await session.execute(
            select(Payment.status, func.count(Payment.id)).where(*status_filters).group_by(Payment.status)
        )
    ).all()

    return RevenueSummary(
        period=period,
        paid_orders=totals[0],
        revenue=Decimal(str(totals[1])),
        discounts_given=Decimal(str(totals[2])),
        by_provider=by_provider,
        by_status={status: count for status, count in status_rows},
    )


@dataclass
class PaymentRow:
    id: int
    telegram_id: int
    username: str | None
    amount_usd: Decimal
    status: str
    provider: str
    created_at: dt.datetime

    @property
    def who(self) -> str:
        return f"@{self.username}" if self.username else str(self.telegram_id)


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
            .offset(max(0, page) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    ).all()

    return PaymentPage(
        rows=[
            PaymentRow(
                id=payment.id,
                telegram_id=payment.telegram_id,
                username=username,
                amount_usd=payment.amount_usd,
                status=payment.status,
                provider=payment.provider,
                created_at=payment.created_at,
            )
            for payment, username in rows
        ],
        page=max(0, page),
        total=total,
    )


@dataclass
class PaymentDetail:
    payment: Payment
    username: str | None
    plan_name: str | None


async def payment_detail(session: AsyncSession, payment_id: int) -> PaymentDetail | None:
    row = (
        await session.execute(
            select(Payment, BotUser.username, Plan.name)
            .outerjoin(BotUser, BotUser.telegram_id == Payment.telegram_id)
            .outerjoin(Plan, Plan.id == Payment.plan_id)
            .where(Payment.id == payment_id)
        )
    ).one_or_none()
    if row is None:
        return None
    payment, username, plan_name = row
    return PaymentDetail(payment=payment, username=username, plan_name=plan_name)


async def resolve_user_query(session: AsyncSession, raw: str) -> int | None:
    """Accepts a numeric Telegram id, "@username" or a bare username.
    Returns None when nothing matches, which the caller reports rather
    than silently falling back to showing every payment."""
    value = raw.strip().lstrip("@")
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return (
        await session.execute(
            select(BotUser.telegram_id).where(func.lower(BotUser.username) == value.lower()).limit(1)
        )
    ).scalar_one_or_none()


@dataclass
class DiscountPerformance:
    used_count: int
    usage_limit: int | None
    paid_payments: int
    revenue: Decimal
    discount_given: Decimal


async def discount_performance(session: AsyncSession, discount_code_id: int) -> DiscountPerformance:
    """`used_count` and `paid_payments` can legitimately differ: the
    counter increments at activation while the payment rows are the
    audit trail. Both are reported rather than one standing in for the
    other."""
    code = await session.get(DiscountCode, discount_code_id)
    row = (
        await session.execute(
            select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount_usd), 0), _discount_given_sum())
            .where(Payment.discount_code_id == discount_code_id, Payment.status == PAID)
        )
    ).one()
    return DiscountPerformance(
        used_count=code.used_count if code is not None else 0,
        usage_limit=code.usage_limit if code is not None else None,
        paid_payments=row[0],
        revenue=Decimal(str(row[1])),
        discount_given=Decimal(str(row[2])),
    )


# --- Reports (epic part 4) -------------------------------------------
#
# Deliberately beside the Financial queries rather than in a module of
# their own: both answer "how is the business doing", and splitting them
# would invite a second definition of revenue or of a period boundary.

#: Live IBSng status costs one round trip per account, so the accounts
#: breakdown checks the newest few and says so rather than letting one
#: screen's cost grow with the customer base.
ACCOUNT_SAMPLE_SIZE = 20


async def signup_count(session: AsyncSession, *, period: str) -> tuple[int, int]:
    """(in period, all time). Counts people who started the bot, which is
    not the same as buyers - the pair makes that visible."""
    start = period_start(period)
    filters = [] if start is None else [BotUser.first_seen_at >= start]
    in_period = (await session.execute(select(func.count(BotUser.id)).where(*filters))).scalar_one()
    all_time = (await session.execute(select(func.count(BotUser.id)))).scalar_one()
    return in_period, all_time


@dataclass
class AccountBreakdown:
    counts: dict[str, int]
    checked: int
    total: int

    @property
    def sampled(self) -> bool:
        return self.checked < self.total


async def account_breakdown(session: AsyncSession, client, *, limit: int = ACCOUNT_SAMPLE_SIZE) -> AccountBreakdown:  # type: ignore[no-untyped-def]
    """Active vs expired can only come from IBSng: VPNUser.expires_at is
    never written by anything in this codebase. Checking every account
    would make this unbounded, so the newest `limit` are checked and both
    numbers are reported - a report that silently sampled would be worse
    than one that says it sampled."""
    from app.services.vpn_users import get_service_status

    total = (await session.execute(select(func.count(VPNUser.id)))).scalar_one()
    usernames = (
        await session.execute(
            select(VPNUser.ibsng_username).order_by(VPNUser.id.desc()).limit(limit)
        )
    ).scalars().all()

    counts: dict[str, int] = {}
    for username in usernames:
        status, _ = await get_service_status(client, username)
        counts[status] = counts.get(status, 0) + 1
    return AccountBreakdown(counts=counts, checked=len(usernames), total=total)


@dataclass
class TrialConversion:
    trials: int
    converted: int

    @property
    def rate(self) -> Decimal:
        if not self.trials:
            return Decimal("0.0")
        return (Decimal(self.converted) * 100 / Decimal(self.trials)).quantize(Decimal("0.1"))


async def trial_conversion(session: AsyncSession, *, period: str) -> TrialConversion:
    """Trials started in the period, and how many of those same people
    have ever paid. The numerator is deliberately NOT period-scoped: a
    trial taken on the 30th and paid on the 2nd is still a conversion."""
    start = period_start(period)
    filters = [VPNUser.is_trial.is_(True)]
    if start is not None:
        filters.append(VPNUser.created_at >= start)

    trial_ids = set(
        (await session.execute(select(VPNUser.telegram_id).where(*filters))).scalars().all()
    )
    if not trial_ids:
        return TrialConversion(trials=0, converted=0)

    payers = set(
        (
            await session.execute(
                select(Payment.telegram_id).where(
                    Payment.status == PAID, Payment.telegram_id.in_(trial_ids)
                )
            )
        ).scalars().all()
    )
    return TrialConversion(trials=len(trial_ids), converted=len(trial_ids & payers))


@dataclass
class PlanSales:
    plan_name: str
    category: str
    orders: int
    revenue: Decimal


async def top_plans(session: AsyncSession, *, period: str, limit: int = 5) -> list[PlanSales]:
    """Ranked by paid orders. Pending and failed rows are excluded, for
    the same reason they are excluded from revenue."""
    start = period_start(period)
    filters = [Payment.status == PAID]
    if start is not None:
        filters.append(_effective_date() >= start)

    rows = (
        await session.execute(
            select(
                Plan.name,
                Plan.category,
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount_usd), 0),
            )
            .join(Plan, Plan.id == Payment.plan_id)
            .where(*filters)
            .group_by(Plan.name, Plan.category)
            .order_by(func.count(Payment.id).desc())
            .limit(limit)
        )
    ).all()
    return [
        PlanSales(plan_name=name, category=category, orders=orders, revenue=Decimal(str(revenue)))
        for name, category, orders, revenue in rows
    ]
