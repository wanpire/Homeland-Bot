from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TutorialPlatform(Base):
    """A device/OS a user can pick (iOS, Android, Windows, macOS) - drives
    which TutorialGuide/OpenVpnProfile is shown. Seed-only for now (see
    migration 0005); admin CRUD for these is out of scope until the full
    admin panel lands."""

    __tablename__ = "tutorial_platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
