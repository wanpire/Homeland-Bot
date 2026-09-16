from __future__ import annotations

import datetime as dt
import secrets
import string

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vpn_user import VPNUser
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError

_CREDENTIAL_CHARS = string.ascii_lowercase + string.digits
_USERNAME_PREFIX = "hl."
_USERNAME_SUFFIX_LEN = 6
_PASSWORD_LEN = 6


class VPNUsernameTakenError(Exception):
    """Raised when a generated username collides locally, in IBSng, or
    (for a trial) when the DB's partial unique index rejects a second
    is_trial=true row for the same telegram_id - all three are the same
    "this account can't be created as requested" situation from the
    caller's point of view."""


class TrialAlreadyUsedError(Exception):
    """Raised when create_vpn_user(is_trial=True) is called for a
    telegram_id that already has a trial VPNUser row. Checked BEFORE
    any IBSng call, so a repeat trial attempt never provisions (and
    orphans) a real account on the shared IBSng instance - unlike
    VPNUsernameTakenError, which can only be detected after the local
    insert, this constraint is knowable up front from a plain query."""


def _random_password(length: int) -> str:
    while True:
        candidate = "".join(secrets.choice(_CREDENTIAL_CHARS) for _ in range(length))
        if any(c.isalpha() for c in candidate) and any(c.isdigit() for c in candidate):
            return candidate


def generate_vpn_credentials() -> tuple[str, str]:
    """Bot-generated, never typed by the user - same scheme for trial
    and (later) paid purchases. Ported from AloBot's generate_vpn_credentials
    with Homeland's own username prefix."""
    suffix = "".join(secrets.choice(_CREDENTIAL_CHARS) for _ in range(_USERNAME_SUFFIX_LEN))
    return f"{_USERNAME_PREFIX}{suffix}", _random_password(_PASSWORD_LEN)


async def create_vpn_user(
    session: AsyncSession,
    client: IBSngClient,
    *,
    telegram_id: int,
    username: str,
    password: str,
    group_name: str,
    data_cap_mb: int,
    plan_id: int | None = None,
    is_trial: bool = False,
) -> VPNUser:
    """The one account-creation path - trial and (later) paid purchases
    both call this, differentiated only by is_trial/plan_id. Sequence:
    local uniqueness pre-checks (both of them avoid creating an orphan
    IBSng account for a request the local DB already knows it must
    reject: a username we already know is taken, and - for a trial - a
    telegram_id that already claimed its one lifetime trial) -> IBSng
    account creation -> local row insert -> IntegrityError as a
    race-condition backstop (two concurrent requests that both passed
    the pre-checks; covers a username collision AND, via the partial
    unique index on is_trial, a duplicate trial claim - both surface as
    the same VPNUsernameTakenError)."""
    existing = await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
    if existing.scalar_one_or_none() is not None:
        raise VPNUsernameTakenError(f"{username!r} already exists locally")

    # Must come BEFORE the IBSng call: the partial unique index would
    # reject the local insert anyway, but only after a real account had
    # already been provisioned on the shared production IBSng instance,
    # leaving it orphaned with no local row pointing at it.
    if is_trial and await has_used_trial(session, telegram_id):
        raise TrialAlreadyUsedError(f"telegram_id {telegram_id} already has a trial account")

    await client.create_user(username=username, password=password, group_name=group_name, credit=data_cap_mb)

    vpn_user = VPNUser(
        telegram_id=telegram_id,
        ibsng_username=username,
        ibsng_group=group_name,
        plan_id=plan_id,
        data_cap_mb=data_cap_mb,
        is_trial=is_trial,
    )
    session.add(vpn_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise VPNUsernameTakenError(f"{username!r} lost a creation race") from exc
    await session.refresh(vpn_user)
    return vpn_user


async def has_used_trial(session: AsyncSession, telegram_id: int) -> bool:
    result = await session.execute(
        select(VPNUser.id).where(VPNUser.telegram_id == telegram_id, VPNUser.is_trial.is_(True)).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def renew_and_change_group(
    session: AsyncSession,
    client: IBSngClient,
    *,
    username: str,
    new_group_name: str,
    new_plan_id: int | None,
    new_data_cap_mb: int,
) -> None:
    """Renews (resets validity) AND moves to a (possibly different)
    group/plan in one IBSng-side action. Updates the locally-tracked
    VPNUser row if this username is tracked (was created through the
    bot) - otherwise this is IBSng-only, no local row to update."""
    await client.renew_user(username=username)
    await client.change_user_group(username=username, group_name=new_group_name)
    vpn_user = (
        await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
    ).scalar_one_or_none()
    if vpn_user is not None:
        vpn_user.ibsng_group = new_group_name
        vpn_user.plan_id = new_plan_id
        vpn_user.data_cap_mb = new_data_cap_mb
        vpn_user.expiry_reminder_sent_at = None
        vpn_user.low_quota_reminder_sent_at = None
        await session.commit()


def parse_ibsng_expiry(raw: str) -> dt.datetime | None:
    """IBSng's nearest_exp_date reads None until an account's first
    connection starts the countdown; once set, confirmed live (on this
    shared instance, via the sibling AloBot project) as "YYYY-MM-DD HH:MM"
    (e.g. "2026-09-23 15:41"). Defensively tries that shape plus a couple
    of common fallbacks, and returns None (treat as unknown, don't crash)
    rather than guess on an unrecognized format."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


async def get_service_status(client: IBSngClient, username: str) -> tuple[str, dt.datetime | None]:
    """Never raises - a status check failing must never crash the screen
    showing it. Returns ("unknown", None) on any IBSng error or
    unparseable date, ("pending", None) when IBSng has no expiry yet
    (never connected), else ("active"|"expired", the parsed datetime)."""
    try:
        raw = await client.get_user_expiry(username=username)
    except IBSngError:
        return "unknown", None
    if not raw:
        return "pending", None
    expiry = parse_ibsng_expiry(raw)
    if expiry is None:
        return "unknown", None
    now = dt.datetime.now(dt.timezone.utc)
    return ("active" if expiry > now else "expired"), expiry


async def get_owned_vpn_user(session: AsyncSession, vpn_user_id: int, telegram_id: int) -> VPNUser | None:
    return (
        await session.execute(
            select(VPNUser).where(VPNUser.id == vpn_user_id, VPNUser.telegram_id == telegram_id)
        )
    ).scalar_one_or_none()


async def list_vpn_users_for_telegram_id(session: AsyncSession, telegram_id: int) -> list[VPNUser]:
    return list(
        (
            await session.execute(
                select(VPNUser).where(VPNUser.telegram_id == telegram_id).order_by(VPNUser.id)
            )
        )
        .scalars()
        .all()
    )
