from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.session import async_session_maker
from app.services.discounts import (
    DiscountCodeInvalidError,
    create_discount_code,
    delete_discount_code,
    discount_price,
    find_best_auto_discount,
    get_discount_code,
    normalize_discount_code,
    set_discount_active,
    update_discount_code,
    validate_discount_code,
)


def _plan_id(seeded_catalog: dict, category: str) -> int:
    return next(p["id"] for p in seeded_catalog["plans"] if p["category"] == category)


@pytest.mark.asyncio
async def test_create_discount_code_normalizes_code_to_uppercase() -> None:
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="  welcome10  ", percent=Decimal("10"), usage_limit=None, plan_ids=None)
    assert discount.code == "WELCOME10"


def test_normalize_discount_code_strips_and_uppercases() -> None:
    assert normalize_discount_code("  hello ") == "HELLO"


def test_discount_price_applies_percent_and_rounds() -> None:
    assert discount_price(Decimal("19.99"), Decimal("10")) == Decimal("17.99")


@pytest.mark.asyncio
async def test_update_discount_code_changes_fields_but_not_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="ORIGINAL", percent=Decimal("10"), usage_limit=5, plan_ids=None)
        updated = await update_discount_code(
            session, discount.id, percent=Decimal("20"), usage_limit=None, plan_ids=[scroll_id], is_public=False
        )
    assert updated.code == "ORIGINAL"
    assert updated.percent == Decimal("20")
    assert updated.usage_limit is None
    assert updated.plan_ids == str(scroll_id)
    assert updated.is_public is False


@pytest.mark.asyncio
async def test_set_discount_active_toggles() -> None:
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="TOGGLE", percent=Decimal("5"), usage_limit=None, plan_ids=None)
        toggled = await set_discount_active(session, discount.id, False)
    assert toggled.is_active is False


@pytest.mark.asyncio
async def test_delete_discount_code_removes_row() -> None:
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="DELME", percent=Decimal("5"), usage_limit=None, plan_ids=None)
        deleted = await delete_discount_code(session, discount.id)
        missing = await get_discount_code(session, discount.id)
    assert deleted is True
    assert missing is None


@pytest.mark.asyncio
async def test_validate_discount_code_raises_for_unknown_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="NOPE", plan_id=scroll_id)


@pytest.mark.asyncio
async def test_validate_discount_code_raises_when_inactive(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="INACTIVE1", percent=Decimal("10"), usage_limit=None, plan_ids=None)
        await set_discount_active(session, discount.id, False)
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="INACTIVE1", plan_id=scroll_id)


@pytest.mark.asyncio
async def test_validate_discount_code_raises_when_exhausted(seeded_catalog: dict) -> None:
    from app.db.models.discount_code import DiscountCode

    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        discount = await create_discount_code(session, code="EXHAUSTED", percent=Decimal("10"), usage_limit=1, plan_ids=None)
        discount.used_count = 1
        await session.commit()
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="EXHAUSTED", plan_id=scroll_id)


@pytest.mark.asyncio
async def test_validate_discount_code_raises_when_plan_not_scoped(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    stream_id = _plan_id(seeded_catalog, "stream")
    async with async_session_maker() as session:
        await create_discount_code(session, code="SCROLLONLY", percent=Decimal("10"), usage_limit=None, plan_ids=[scroll_id])
        with pytest.raises(DiscountCodeInvalidError):
            await validate_discount_code(session, code="SCROLLONLY", plan_id=stream_id)


@pytest.mark.asyncio
async def test_validate_discount_code_succeeds_for_valid_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        await create_discount_code(session, code="VALID10", percent=Decimal("10"), usage_limit=None, plan_ids=None)
        discount = await validate_discount_code(session, code="valid10", plan_id=scroll_id)
    assert discount.code == "VALID10"


@pytest.mark.asyncio
async def test_find_best_auto_discount_picks_highest_percent_public_code(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        await create_discount_code(session, code="LOW", percent=Decimal("5"), usage_limit=None, plan_ids=None, is_public=True)
        await create_discount_code(session, code="HIGH", percent=Decimal("25"), usage_limit=None, plan_ids=None, is_public=True)
        best = await find_best_auto_discount(session, scroll_id)
    assert best.code == "HIGH"


@pytest.mark.asyncio
async def test_find_best_auto_discount_ignores_private_codes(seeded_catalog: dict) -> None:
    scroll_id = _plan_id(seeded_catalog, "scroll")
    async with async_session_maker() as session:
        await create_discount_code(session, code="PUBLIC5", percent=Decimal("5"), usage_limit=None, plan_ids=None, is_public=True)
        await create_discount_code(session, code="PRIVATE99", percent=Decimal("99"), usage_limit=None, plan_ids=None, is_public=False)
        best = await find_best_auto_discount(session, scroll_id)
    assert best.code == "PUBLIC5"


@pytest.mark.asyncio
async def test_increment_discount_usage_increases_used_count() -> None:
    from app.services.discounts import increment_discount_usage

    async with async_session_maker() as session:
        discount = await create_discount_code(
            session, code="BUMP10", percent=Decimal("10"), usage_limit=None, plan_ids=None,
        )
    assert discount.used_count == 0

    async with async_session_maker() as session:
        await increment_discount_usage(session, discount.id)

    async with async_session_maker() as session:
        refreshed = await get_discount_code(session, discount.id)
    assert refreshed.used_count == 1
