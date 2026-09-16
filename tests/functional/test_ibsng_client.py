from __future__ import annotations

import pytest

from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngUserExistsError, IBSngUserNotFoundError
from tests.fakes.fake_ibsng_server import FakeIBSngServer


@pytest.mark.asyncio
async def test_list_groups_returns_seeded_groups(ibsng_server: FakeIBSngServer) -> None:
    """IBSngClient.list_groups() is a faithful, unfiltered transport - it
    returns every group the server has, Homeland's and AloBot's alike.
    Namespace filtering is sync_groups()'s job (see test_groups.py), not
    this client's - a shared IBSng instance means list_groups() legitimately
    sees groups outside Homeland's own namespace."""
    async with IBSngClient() as client:
        groups = await client.list_groups()
    assert groups == ibsng_server._groups  # noqa: SLF001


@pytest.mark.asyncio
async def test_create_user_then_get_info(ibsng_server: FakeIBSngServer) -> None:
    async with IBSngClient() as client:
        await client.create_user(username="alice_vpn", password="pw123", group_name="HL-1M", credit=5120)
        info = await client.get_user_info(username="alice_vpn")

    assert info is not None


@pytest.mark.asyncio
async def test_create_user_twice_raises(ibsng_server: FakeIBSngServer) -> None:
    async with IBSngClient() as client:
        await client.create_user(username="bob_vpn", password="pw123", group_name="HL-1M", credit=5120)
        with pytest.raises(IBSngUserExistsError):
            await client.create_user(username="bob_vpn", password="pw123", group_name="HL-1M", credit=5120)


@pytest.mark.asyncio
async def test_get_user_expiry_reads_attrs(ibsng_server: FakeIBSngServer) -> None:
    async with IBSngClient() as client:
        await client.create_user(username="carol_vpn", password="pw123", group_name="HL-1M", credit=5120)
    ibsng_server.set_user_attr("carol_vpn", "nearest_exp_date", "2026-10-01 12:00")

    async with IBSngClient() as client:
        expiry = await client.get_user_expiry(username="carol_vpn")
    assert expiry == "2026-10-01 12:00"


@pytest.mark.asyncio
async def test_get_user_expiry_returns_none_for_unknown_user(ibsng_server: FakeIBSngServer) -> None:
    """Degrades to None like get_user_group/get_user_password rather than
    raising IBSngError, so a missing IBSng account isn't a crash."""
    async with IBSngClient() as client:
        assert await client.get_user_expiry(username="nobody_vpn") is None


@pytest.mark.asyncio
async def test_change_user_group(ibsng_server: FakeIBSngServer) -> None:
    async with IBSngClient() as client:
        await client.create_user(username="dave_vpn", password="pw123", group_name="HL-1M", credit=5120)
        await client.change_user_group(username="dave_vpn", group_name="HL-2M")
        group = await client.get_user_group(username="dave_vpn")
    assert group == "HL-2M"


@pytest.mark.asyncio
async def test_change_user_password_and_verify(ibsng_server: FakeIBSngServer) -> None:
    async with IBSngClient() as client:
        await client.create_user(username="erin_vpn", password="old-pw", group_name="HL-1M", credit=5120)
        await client.change_user_password(username="erin_vpn", new_password="new-pw")
        assert await client.verify_user_credentials(username="erin_vpn", password="new-pw") is True
        assert await client.verify_user_credentials(username="erin_vpn", password="old-pw") is False


@pytest.mark.asyncio
async def test_lock_and_delete_user(ibsng_server: FakeIBSngServer) -> None:
    async with IBSngClient() as client:
        await client.create_user(username="frank_vpn", password="pw123", group_name="HL-1M", credit=5120)
        await client.lock_user(username="frank_vpn", locked=True)
        await client.delete_user(username="frank_vpn")
        with pytest.raises(IBSngUserNotFoundError):
            await client.change_user_group(username="frank_vpn", group_name="HL-1M")


@pytest.mark.asyncio
async def test_renew_user_is_idempotent() -> None:
    from app.services.ibsng.client import IBSngClient

    async with IBSngClient() as client:
        await client.create_user(username="renew-target", password="abc123", group_name="Trial-Iran", credit=1024)
        await client.renew_user(username="renew-target")
        await client.renew_user(username="renew-target")  # second call must not raise


@pytest.mark.asyncio
async def test_renew_user_raises_not_found_for_unknown_username() -> None:
    from app.services.ibsng.client import IBSngClient
    from app.services.ibsng.exceptions import IBSngUserNotFoundError

    async with IBSngClient() as client:
        with pytest.raises(IBSngUserNotFoundError):
            await client.renew_user(username="does-not-exist")
