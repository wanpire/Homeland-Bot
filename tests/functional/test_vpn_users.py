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
    """Exercises the DB partial-unique-index backstop from Task 1, via
    create_vpn_user's IntegrityError catch - a second trial attempt for
    the same telegram_id must surface as the same VPNUsernameTakenError,
    not an unhandled IntegrityError."""
    from app.services.vpn_users import VPNUsernameTakenError, create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=604, username="hl.trial01", password="ab12cd",
            group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
        )

    async with async_session_maker() as session, IBSngClient() as client:
        with pytest.raises(VPNUsernameTakenError):
            await create_vpn_user(
                session, client, telegram_id=604, username="hl.trial02", password="ef34gh",
                group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
            )


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
