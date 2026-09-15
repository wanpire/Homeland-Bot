from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OpenVpnProfile(Base):
    """An OpenVPN .ovpn config file (or inline text) an admin uploads.
    platform_id=NULL means "matches any platform" - a platform-specific
    row, if one exists, takes priority over the generic one (see
    services.tutorials.find_matching_profile). No uniqueness constraint:
    like AloBot's original, admin discipline plus "most specific match
    wins" is enough here, there's no user-facing harm from a duplicate."""

    __tablename__ = "openvpn_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    platform_id: Mapped[int | None] = mapped_column(ForeignKey("tutorial_platforms.id"), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "document" | "photo" | "video"
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
