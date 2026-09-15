from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TutorialProtocol(Base):
    """L2TP or OpenVPN - the two protocols Homeland offers (spec §9).
    Seed-only, same as TutorialPlatform."""

    __tablename__ = "tutorial_protocols"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
