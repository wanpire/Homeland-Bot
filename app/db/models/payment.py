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
    failed/refunded), separate from the raw Plisio invoice statuses
    recorded per-callback in PaymentStatusEvent - never conflate the two:
    Plisio has finer states (new/pending/pending internal) that don't
    need their own Payment.status value, since nothing user-facing or
    provisioning-related happens until "completed"."""

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
    # Plisio's callback "amount" field, in the coin the buyer chose
    # (e.g. USDT) - NOT necessarily USD, despite amount_usd/original_amount_usd
    # above being USD. Never presented to a user as a dollar figure (see
    # app/webhook.py's partially_paid handling) - stored for audit/support
    # cross-reference against the Plisio dashboard only.
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    provider: Mapped[str] = mapped_column(String(16), default="plisio")
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # pending -> paid | partially_paid | failed | refunded
    status: Mapped[str] = mapped_column(String(16), default="pending")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
