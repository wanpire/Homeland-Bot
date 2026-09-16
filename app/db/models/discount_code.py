from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiscountCode(Base):
    """A percent-off code, scoped to zero or more Plans via a comma-joined
    `plan_ids` string (NULL = applies to every plan) - Homeland's flat
    catalog has no `categories` dimension like AloBot's DiscountCode, so
    this is the one field that differs from the ported original.
    `used_count` stays at its default of 0 until the Buy/payments plan
    wires up the increment call (see the admin panel spec §1/§7) -
    nothing in this codebase increments it yet."""

    __tablename__ = "discount_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    plan_ids: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
