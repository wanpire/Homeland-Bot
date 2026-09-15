from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TutorialGuide(Base):
    """The (platform, protocol) -> setup-instructions mapping. platform_id
    is NULL for OpenVPN (one shared guide, not per-platform - spec §2)
    and required for L2TP (4 separate guides). Two partial unique indexes
    replace one plain unique constraint because Postgres treats every
    NULL as distinct in a unique constraint - without the split, a
    second NULL-platform OpenVPN guide could be inserted with no error."""

    __tablename__ = "tutorial_guides"
    __table_args__ = (
        Index(
            "uq_tutorial_guides_no_platform", "protocol_id",
            unique=True, postgresql_where=text("platform_id IS NULL"),
        ),
        Index(
            "uq_tutorial_guides_with_platform", "platform_id", "protocol_id",
            unique=True, postgresql_where=text("platform_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int | None] = mapped_column(ForeignKey("tutorial_platforms.id"), nullable=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("tutorial_protocols.id"))
    # Optional caption alongside media_file_id - guides are expected to
    # be purely file-based (admin uploads a photo/document/video), but
    # this stays available for a text-only guide too.
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "photo" | "document" | "video"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
