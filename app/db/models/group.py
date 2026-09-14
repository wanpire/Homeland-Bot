from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Group(Base):
    """A locally cached copy of an IBSng group name, kept in sync via
    services.groups.sync_groups(). Exists so admin can pick a real,
    existing IBSng group when binding/rebinding a Plan, without calling
    IBSng on every keystroke."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    synced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
