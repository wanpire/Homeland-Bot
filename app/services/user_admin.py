"""Everything an admin needs to know about one customer, gathered once.

Pulled together here rather than in the handler because it spans four
sources - the bot user row, their VPN services, live IBSng status, and
their payment history - and a screen that assembles that itself would be
impossible to test without a Telegram update.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser
from app.db.models.payment import Payment
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.services.ibsng.client import IBSngClient
from app.services.vpn_users import get_service_status, has_used_trial

#: Each service costs one IBSng round trip for its live status, so a
#: customer with a long history does not turn one screen into a dozen
#: network calls. The newest are the ones an admin is asking about.
MAX_LIVE_SERVICES = 5


@dataclass
class ServiceLine:
    vpn_user_id: int
    ibsng_username: str
    plan_name: str
    is_trial: bool
    status: str  # active | expired | pending | unknown
    expires_at: dt.datetime | None


@dataclass
class PaymentTotals:
    paid: int = 0
    pending: int = 0
    failed: int = 0
    other: int = 0
    total_paid_usd: Decimal = Decimal("0.00")
    last_paid_at: dt.datetime | None = None


@dataclass
class UserOverview:
    telegram_id: int
    username: str | None
    first_seen_at: dt.datetime | None
    language: str | None
    is_blocked: bool
    trial_used: bool
    services: list[ServiceLine] = field(default_factory=list)
    total_services: int = 0
    payments: PaymentTotals = field(default_factory=PaymentTotals)

    @property
    def truncated_services(self) -> int:
        return max(0, self.total_services - len(self.services))

    @property
    def display_name(self) -> str:
        return f"@{self.username}" if self.username else str(self.telegram_id)


async def user_overview(
    session: AsyncSession, client: IBSngClient, telegram_id: int
) -> UserOverview | None:
    """None when the id has never interacted with the bot. The IBSng
    client is passed in so the caller owns its lifetime and a test can
    hand over the fake."""
    bot_user = (
        await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if bot_user is None:
        return None

    overview = UserOverview(
        telegram_id=bot_user.telegram_id,
        username=bot_user.username,
        first_seen_at=bot_user.first_seen_at,
        language=bot_user.language,
        is_blocked=bot_user.is_blocked,
        trial_used=await has_used_trial(session, telegram_id),
    )

    rows = (
        await session.execute(
            select(VPNUser, Plan.name)
            .outerjoin(Plan, Plan.id == VPNUser.plan_id)
            .where(VPNUser.telegram_id == telegram_id)
            .order_by(VPNUser.id.desc())
        )
    ).all()
    overview.total_services = len(rows)

    for vpn_user, plan_name in rows[:MAX_LIVE_SERVICES]:
        # get_service_status never raises: an IBSng outage degrades one
        # line to "unknown" rather than blanking the screen an admin
        # opened precisely because something is wrong.
        status, expires_at = await get_service_status(client, vpn_user.ibsng_username)
        overview.services.append(
            ServiceLine(
                vpn_user_id=vpn_user.id,
                ibsng_username=vpn_user.ibsng_username,
                # VPNUser.expires_at is deliberately ignored - nothing in
                # the codebase ever writes it, so it is NULL for every
                # row and would read as "no expiry" for a live account.
                plan_name=plan_name or vpn_user.ibsng_group,
                is_trial=vpn_user.is_trial,
                status=status,
                expires_at=expires_at,
            )
        )

    overview.payments = await _payment_totals(session, telegram_id)
    return overview


async def _payment_totals(session: AsyncSession, telegram_id: int) -> PaymentTotals:
    totals = PaymentTotals()
    rows = (
        await session.execute(
            select(Payment.status, func.count(Payment.id), func.coalesce(func.sum(Payment.amount_usd), 0))
            .where(Payment.telegram_id == telegram_id)
            .group_by(Payment.status)
        )
    ).all()
    for status, count, amount in rows:
        if status == "paid":
            totals.paid = count
            totals.total_paid_usd = Decimal(str(amount))
        elif status == "pending":
            totals.pending = count
        elif status == "failed":
            totals.failed = count
        else:
            totals.other += count

    totals.last_paid_at = (
        await session.execute(
            select(func.max(func.coalesce(Payment.resolved_at, Payment.created_at))).where(
                Payment.telegram_id == telegram_id, Payment.status == "paid"
            )
        )
    ).scalar_one_or_none()
    return totals
