from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OwnershipTransfer(Base):
    """One offer to move a VPN account to another Telegram user. The
    account moves only when the named recipient accepts (see
    app/services/ownership.py); every row is kept as the audit trail."""

    __tablename__ = "ownership_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    vpn_user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id"), index=True)
    from_telegram_id: Mapped[int] = mapped_column(BigInteger)
    to_telegram_id: Mapped[int] = mapped_column(BigInteger)
    #: pending | accepted | declined | cancelled | expired
    status: Mapped[str] = mapped_column(String(16), default="pending")
    #: The recipient's offer message, edited when the owner cancels.
    offer_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
