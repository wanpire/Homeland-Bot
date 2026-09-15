from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VPNUser(Base):
    """An owned Homeland VPN account. data_cap_mb snapshots Plan.data_cap_mb
    at purchase/renewal time, so a later plan price/cap edit never
    retroactively changes an existing subscription (spec §5) - mirrors
    how the payment's charged amount is snapshotted rather than
    recomputed from the current plan price.

    expires_at/expiry_reminder_sent_at are read/written the same way
    AloBot's did (live from IBSng, not cached); low_quota_reminder_sent_at
    is new - see docs/superpowers/specs/2026-09-14-homeland-bot-design.md
    §8. Both reminder timestamps are cleared on renewal so the next
    cycle gets a fresh reminder."""

    __tablename__ = "vpn_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ibsng_username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ibsng_group: Mapped[str] = mapped_column(String(64))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    data_cap_mb: Mapped[int] = mapped_column(Integer)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    low_quota_reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
