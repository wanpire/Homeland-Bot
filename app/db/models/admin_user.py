from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminUser(Base):
    """Admin-added admins with a permission level, on top of the
    always-full-access bootstrap admins from ADMIN_IDS (see
    app.services.admin_users). level is one of the ordered tiers in
    app.services.admin_users.LEVELS - "support" < "sales" < "full"."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    level: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
