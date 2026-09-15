from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Plan(Base):
    """One of Homeland's flat, fixed sale plans - a single `category`
    field (scroll/stream/trial), no location/user-count matrix like
    AloBot's Service (spec §4). Admin can edit price/group_name/
    is_active but never creates a new plan through the bot; new plans
    are a schema/seed change, not an admin action."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16), index=True)
    duration_days: Mapped[int] = mapped_column(Integer)
    data_cap_mb: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    group_name: Mapped[str] = mapped_column(String(64), ForeignKey("groups.name"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
