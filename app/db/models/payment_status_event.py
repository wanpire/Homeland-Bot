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
