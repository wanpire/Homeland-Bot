from __future__ import annotations

import pytest

from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngUserExistsError, IBSngUserNotFoundError


@pytest.mark.asyncio
async def test_list_groups_returns_seeded_groups(ibsng_server):
    async with IBSngClient() as client:
        groups = await client.list_groups()
    assert groups == ["HL-2W", "HL-1M", "HL-2M", "HL-3M"]


@pytest.mark.asyncio
async def test_create_user_then_get_info(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="alice_vpn", password="pw123", group_name="HL-1M", credit=5120)
        info = await client.get_user_info(username="alice_vpn")

    assert info is not None


@pytest.mark.asyncio
async def test_create_user_twice_raises(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="bob_vpn", password="pw123", group_name="HL-1M", credit=5120)
        with pytest.raises(IBSngUserExistsError):
            await client.create_user(username="bob_vpn", password="pw123", group_name="HL-1M", credit=5120)


@pytest.mark.asyncio
async def test_get_user_expiry_reads_attrs(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="carol_vpn", password="pw123", group_name="HL-1M", credit=5120)
    ibsng_server.set_user_attr("carol_vpn", "nearest_exp_date", "2026-10-01 12:00")

    async with IBSngClient() as client:
        expiry = await client.get_user_expiry(username="carol_vpn")
    assert expiry == "2026-10-01 12:00"


@pytest.mark.asyncio
async def test_change_user_group(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="dave_vpn", password="pw123", group_name="HL-1M", credit=5120)
        await client.change_user_group(username="dave_vpn", group_name="HL-2M")
        group = await client.get_user_group(username="dave_vpn")
    assert group == "HL-2M"


@pytest.mark.asyncio
async def test_change_user_password_and_verify(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="erin_vpn", password="old-pw", group_name="HL-1M", credit=5120)
        await client.change_user_password(username="erin_vpn", new_password="new-pw")
        assert await client.verify_user_credentials(username="erin_vpn", password="new-pw") is True
        assert await client.verify_user_credentials(username="erin_vpn", password="old-pw") is False


@pytest.mark.asyncio
async def test_lock_and_delete_user(ibsng_server):
    async with IBSngClient() as client:
        await client.create_user(username="frank_vpn", password="pw123", group_name="HL-1M", credit=5120)
        await client.lock_user(username="frank_vpn", locked=True)
        await client.delete_user(username="frank_vpn")
        with pytest.raises(IBSngUserNotFoundError):
            await client.change_user_group(username="frank_vpn", group_name="HL-1M")
