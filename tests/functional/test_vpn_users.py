from __future__ import annotations

import pytest

from app.db.session import async_session_maker
from app.services.ibsng.client import IBSngClient
from tests.fakes.fake_ibsng_server import FakeIBSngServer


def test_generate_vpn_credentials_shape() -> None:
    from app.services.vpn_users import generate_vpn_credentials

    username, password = generate_vpn_credentials()
    assert username.startswith("hl.")
    assert len(username) == len("hl.") + 6
    assert len(password) == 6
    assert any(c.isalpha() for c in password)
    assert any(c.isdigit() for c in password)


def test_generate_vpn_credentials_are_random() -> None:
    from app.services.vpn_users import generate_vpn_credentials

    pairs = {generate_vpn_credentials() for _ in range(20)}
    assert len(pairs) == 20


@pytest.mark.asyncio
async def test_create_vpn_user_creates_ibsng_and_local_row(ibsng_server: FakeIBSngServer) -> None:
    from app.services.vpn_users import create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client,
            telegram_id=601, username="hl.abc123", password="ab12cd",
            group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
        )

    assert vpn_user.ibsng_username == "hl.abc123"
    assert vpn_user.ibsng_group == "Trial-Iran"
    assert vpn_user.is_trial is True
    assert vpn_user.data_cap_mb == 1024

    async with IBSngClient() as client:
        info = await client.get_user_info(username="hl.abc123")
    assert info is not None


@pytest.mark.asyncio
async def test_create_vpn_user_rejects_duplicate_local_username(ibsng_server: FakeIBSngServer) -> None:
    from app.services.vpn_users import VPNUsernameTakenError, create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=602, username="hl.dup001", password="ab12cd",
            group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
        )

    async with async_session_maker() as session, IBSngClient() as client:
        with pytest.raises(VPNUsernameTakenError):
            await create_vpn_user(
                session, client, telegram_id=603, username="hl.dup001", password="ef34gh",
                group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
            )


@pytest.mark.asyncio
async def test_create_vpn_user_rejects_second_trial_for_same_telegram_id(ibsng_server: FakeIBSngServer) -> None:
    """A second trial attempt for the same telegram_id must be rejected
    BEFORE IBSng is touched, as TrialAlreadyUsedError - distinct from
    VPNUsernameTakenError, since retrying with a fresh username can never
    help (the blocker is the telegram_id) and each retry would otherwise
    orphan another real account on the shared IBSng instance.

    The DB's partial unique index remains the backstop for the genuine
    concurrent race, which this pre-check can't see."""
    from app.services.vpn_users import TrialAlreadyUsedError, create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=604, username="hl.trial01", password="ab12cd",
            group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
        )
    assert ibsng_server.created_usernames() == ["hl.trial01"]

    async with async_session_maker() as session, IBSngClient() as client:
        with pytest.raises(TrialAlreadyUsedError):
            await create_vpn_user(
                session, client, telegram_id=604, username="hl.trial02", password="ef34gh",
                group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
            )

    # No account was provisioned for the rejected attempt - not even an
    # unnamed one from a half-finished create_user.
    assert ibsng_server.created_usernames() == ["hl.trial01"]
    assert ibsng_server.user_count() == 1


@pytest.mark.asyncio
async def test_create_vpn_user_allows_a_second_non_trial_account(ibsng_server: FakeIBSngServer) -> None:
    """The trial-once pre-check must be scoped to is_trial=True only -
    a user is allowed any number of paid accounts (Buy/Renew, later)."""
    from app.services.vpn_users import create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=606, username="hl.paid001", password="ab12cd",
            group_name="1M-1U-Iran-10G", data_cap_mb=10240, is_trial=True,
        )

    async with async_session_maker() as session, IBSngClient() as client:
        second = await create_vpn_user(
            session, client, telegram_id=606, username="hl.paid002", password="ef34gh",
            group_name="1M-1U-Iran-10G", data_cap_mb=10240, is_trial=False,
        )
    assert second.is_trial is False
    assert ibsng_server.created_usernames() == ["hl.paid001", "hl.paid002"]


@pytest.mark.asyncio
async def test_has_used_trial() -> None:
    from app.services.vpn_users import has_used_trial

    async with async_session_maker() as session:
        assert await has_used_trial(session, 605) is False

    async with async_session_maker() as session:
        from app.db.models.vpn_user import VPNUser

        session.add(VPNUser(telegram_id=605, ibsng_username="hl.hastrial", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    async with async_session_maker() as session:
        assert await has_used_trial(session, 605) is True


@pytest.mark.asyncio
async def test_has_used_trial_ignores_prior_trial_when_limit_disabled() -> None:
    from app.db.models.vpn_user import VPNUser
    from app.services.app_config import set_config
    from app.services.vpn_users import has_used_trial

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=607, ibsng_username="hl.limitoff", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    async with async_session_maker() as session:
        assert await has_used_trial(session, 607) is True

    async with async_session_maker() as session:
        await set_config(session, "trial_limit_enabled", "false")

    async with async_session_maker() as session:
        assert await has_used_trial(session, 607) is False

    async with async_session_maker() as session:
        await set_config(session, "trial_limit_enabled", "true")

    async with async_session_maker() as session:
        assert await has_used_trial(session, 607) is True


@pytest.mark.asyncio
async def test_renew_and_change_group_updates_tracked_vpn_user(seeded_catalog: dict) -> None:
    from sqlalchemy import select

    from app.db.models.vpn_user import VPNUser
    from app.db.session import async_session_maker
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import create_vpn_user, generate_vpn_credentials, renew_and_change_group

    scroll_plans = [p for p in seeded_catalog["plans"] if p["category"] == "scroll"]
    old_plan, new_plan = scroll_plans[0], scroll_plans[1]
    username, password = generate_vpn_credentials()

    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client, telegram_id=12345, username=username, password=password,
            group_name=old_plan["group_name"], data_cap_mb=old_plan["data_cap_mb"], plan_id=old_plan["id"],
        )

    async with async_session_maker() as session, IBSngClient() as client:
        await renew_and_change_group(
            session, client, username=username, new_group_name=new_plan["group_name"],
            new_plan_id=new_plan["id"], new_data_cap_mb=new_plan["data_cap_mb"],
        )

    async with async_session_maker() as session:
        refreshed = (await session.execute(select(VPNUser).where(VPNUser.id == vpn_user.id))).scalar_one()
    assert refreshed.ibsng_group == new_plan["group_name"]
    assert refreshed.plan_id == new_plan["id"]
    assert refreshed.data_cap_mb == new_plan["data_cap_mb"]


@pytest.mark.asyncio
async def test_renew_and_change_group_is_ibsng_only_when_no_local_row(seeded_catalog: dict) -> None:
    from sqlalchemy import select

    from app.db.models.vpn_user import VPNUser
    from app.db.session import async_session_maker
    from app.services.ibsng.client import IBSngClient
    from app.services.vpn_users import renew_and_change_group

    scroll_plan = next(p for p in seeded_catalog["plans"] if p["category"] == "scroll")

    async with IBSngClient() as client:
        await client.create_user(username="ibsng-only-user", password="abc123", group_name="Trial-Iran", credit=512)

    async with async_session_maker() as session, IBSngClient() as client:
        await renew_and_change_group(
            session, client, username="ibsng-only-user", new_group_name=scroll_plan["group_name"],
            new_plan_id=scroll_plan["id"], new_data_cap_mb=scroll_plan["data_cap_mb"],
        )

    async with async_session_maker() as session:
        rows = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == "ibsng-only-user"))).scalars().all()
    assert list(rows) == []
