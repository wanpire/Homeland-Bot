"""Consent-based account transfers for My Services.

"Ownership" is `vpn_users.telegram_id`, exactly as in AloBot: whoever it
names sees the account in My Services and can renew it, reset its
password or transfer it. AloBot moves the account the moment its owner
confirms. Here the owner only makes an offer, and the account moves when
the named recipient accepts it. That closes AloBot's gaps: a mistyped or
stale @username, and no record of who moved what.

Every settle function locks the transfer row and the account row, and
re-checks everything against the database. Callback data is just a
string, and a request can go stale (the account changed hands, or 24
hours passed) between the offer and the tap.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bot_user import BotUser
from app.db.models.ownership_transfer import OwnershipTransfer
from app.db.models.vpn_user import VPNUser

PENDING = "pending"
ACCEPTED = "accepted"
DECLINED = "declined"
CANCELLED = "cancelled"
EXPIRED = "expired"

TRANSFER_TTL = dt.timedelta(hours=24)

#: resolve_recipient outcomes besides a BotUser.
NOT_FOUND = "not_found"
SELF = "self"
AMBIGUOUS = "ambiguous"


async def resolve_recipient(session: AsyncSession, raw: str, *, owner_telegram_id: int) -> BotUser | str:
    """A bot user named by numeric Telegram ID or @username. Only people
    who have started the bot qualify, because the offer has to reach
    them. An @username is matched case-insensitively against the one
    recorded when each user was last seen. If several rows ever held it,
    this answers AMBIGUOUS instead of guessing."""
    text = raw.strip()
    if text.lstrip("-").isdigit():
        candidates = list(
            (await session.execute(select(BotUser).where(BotUser.telegram_id == int(text)))).scalars()
        )
    else:
        username = text.lstrip("@")
        if not username:
            return NOT_FOUND
        candidates = list(
            (
                await session.execute(select(BotUser).where(func.lower(BotUser.username) == username.lower()))
            ).scalars()
        )
    candidates = [c for c in candidates if not c.is_blocked]
    if not candidates:
        return NOT_FOUND
    if len(candidates) > 1:
        return AMBIGUOUS
    if candidates[0].telegram_id == owner_telegram_id:
        return SELF
    return candidates[0]


def display_name(bot_user: BotUser | None, fallback: str) -> str:
    """"@username" when known, otherwise the caller's localized
    "user <id>" string."""
    if bot_user is not None and bot_user.username:
        return f"@{bot_user.username}"
    return fallback


async def get_bot_user(session: AsyncSession, telegram_id: int) -> BotUser | None:
    return (await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))).scalar_one_or_none()


async def create_transfer(
    session: AsyncSession, *, vpn_user_id: int, owner_telegram_id: int, recipient_telegram_id: int
) -> OwnershipTransfer | None:
    """A new pending offer. None unless the owner still owns the account
    and the recipient is someone else. Any older pending offer for the
    account is cancelled, so only the newest one can ever be accepted."""
    if recipient_telegram_id == owner_telegram_id:
        return None
    vpn_user = (
        await session.execute(
            select(VPNUser)
            .where(VPNUser.id == vpn_user_id, VPNUser.telegram_id == owner_telegram_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if vpn_user is None:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    await session.execute(
        update(OwnershipTransfer)
        .where(OwnershipTransfer.vpn_user_id == vpn_user_id, OwnershipTransfer.status == PENDING)
        .values(status=CANCELLED, resolved_at=now)
    )
    transfer = OwnershipTransfer(
        vpn_user_id=vpn_user_id,
        from_telegram_id=owner_telegram_id,
        to_telegram_id=recipient_telegram_id,
        status=PENDING,
    )
    session.add(transfer)
    await session.commit()
    await session.refresh(transfer)
    return transfer


@dataclass
class Settled:
    """What a settle call did. `status` is the row's status afterwards;
    `changed` is False when the tap found the request already settled or
    invalid, and nothing happened."""

    transfer: OwnershipTransfer | None
    vpn_user: VPNUser | None
    status: str
    changed: bool


async def _lock(session: AsyncSession, transfer_id: int) -> tuple[OwnershipTransfer | None, VPNUser | None]:
    transfer = (
        await session.execute(
            select(OwnershipTransfer).where(OwnershipTransfer.id == transfer_id).with_for_update()
        )
    ).scalar_one_or_none()
    if transfer is None:
        return None, None
    vpn_user = (
        await session.execute(select(VPNUser).where(VPNUser.id == transfer.vpn_user_id).with_for_update())
    ).scalar_one_or_none()
    return transfer, vpn_user


def _is_expired(transfer: OwnershipTransfer, now: dt.datetime) -> bool:
    created = transfer.created_at if transfer.created_at.tzinfo else transfer.created_at.replace(tzinfo=dt.timezone.utc)
    return now - created >= TRANSFER_TTL


async def _finish(session: AsyncSession, transfer: OwnershipTransfer, status: str, now: dt.datetime) -> None:
    transfer.status = status
    transfer.resolved_at = now
    await session.commit()


async def accept_transfer(session: AsyncSession, *, transfer_id: int, telegram_id: int) -> Settled:
    """Only the named recipient may accept, only while the offer is
    pending and under 24h old, and only if the offering owner still owns
    the account. Accepting also clears the password-reset cooldown: the
    previous owner may still know the password, and the new owner must
    be able to change it straight away."""
    transfer, vpn_user = await _lock(session, transfer_id)
    if transfer is None or transfer.to_telegram_id != telegram_id:
        return Settled(None, None, "invalid", False)
    if transfer.status != PENDING:
        return Settled(transfer, vpn_user, transfer.status, False)
    now = dt.datetime.now(dt.timezone.utc)
    if _is_expired(transfer, now):
        await _finish(session, transfer, EXPIRED, now)
        return Settled(transfer, vpn_user, EXPIRED, False)
    if vpn_user is None or vpn_user.telegram_id != transfer.from_telegram_id:
        await _finish(session, transfer, CANCELLED, now)
        return Settled(transfer, vpn_user, CANCELLED, False)

    vpn_user.telegram_id = transfer.to_telegram_id
    vpn_user.password_changed_at = None
    await _finish(session, transfer, ACCEPTED, now)
    return Settled(transfer, vpn_user, ACCEPTED, True)


async def decline_transfer(session: AsyncSession, *, transfer_id: int, telegram_id: int) -> Settled:
    transfer, vpn_user = await _lock(session, transfer_id)
    if transfer is None or transfer.to_telegram_id != telegram_id:
        return Settled(None, None, "invalid", False)
    if transfer.status != PENDING:
        return Settled(transfer, vpn_user, transfer.status, False)
    await _finish(session, transfer, DECLINED, dt.datetime.now(dt.timezone.utc))
    return Settled(transfer, vpn_user, DECLINED, True)


async def cancel_transfer(session: AsyncSession, *, transfer_id: int, telegram_id: int) -> Settled:
    transfer, vpn_user = await _lock(session, transfer_id)
    if transfer is None or transfer.from_telegram_id != telegram_id:
        return Settled(None, None, "invalid", False)
    if transfer.status != PENDING:
        return Settled(transfer, vpn_user, transfer.status, False)
    await _finish(session, transfer, CANCELLED, dt.datetime.now(dt.timezone.utc))
    return Settled(transfer, vpn_user, CANCELLED, True)


async def record_offer_message(session: AsyncSession, transfer_id: int, message_id: int) -> None:
    transfer = await session.get(OwnershipTransfer, transfer_id)
    if transfer is not None:
        transfer.offer_message_id = message_id
        await session.commit()


async def mark_unreachable(session: AsyncSession, transfer_id: int) -> None:
    transfer = await session.get(OwnershipTransfer, transfer_id)
    if transfer is not None and transfer.status == PENDING:
        await _finish(session, transfer, CANCELLED, dt.datetime.now(dt.timezone.utc))
