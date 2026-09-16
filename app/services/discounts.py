from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discount_code import DiscountCode


class DiscountCodeInvalidError(Exception):
    """Raised by validate_discount_code with a human-readable reason -
    not-found / inactive / exhausted / not scoped to this plan."""


def normalize_discount_code(code: str) -> str:
    return code.strip().upper()


def discount_price(original: Decimal, percent: Decimal) -> Decimal:
    discounted = original * (Decimal("100") - percent) / Decimal("100")
    return discounted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _plan_ids_str(plan_ids: list[int] | None) -> str | None:
    return ",".join(str(p) for p in plan_ids) if plan_ids else None


async def create_discount_code(
    session: AsyncSession,
    *,
    code: str,
    percent: Decimal,
    usage_limit: int | None,
    plan_ids: list[int] | None,
    is_public: bool = True,
) -> DiscountCode:
    discount = DiscountCode(
        code=normalize_discount_code(code),
        percent=percent,
        usage_limit=usage_limit,
        plan_ids=_plan_ids_str(plan_ids),
        is_public=is_public,
    )
    session.add(discount)
    await session.commit()
    await session.refresh(discount)
    return discount


async def update_discount_code(
    session: AsyncSession,
    discount_code_id: int,
    *,
    percent: Decimal,
    usage_limit: int | None,
    plan_ids: list[int] | None,
    is_public: bool,
) -> DiscountCode | None:
    """The code text itself is never editable after creation - matching
    AloBot, and avoiding the ambiguity of what happens to in-flight uses
    of the old code text."""
    discount = await session.get(DiscountCode, discount_code_id)
    if discount is None:
        return None
    discount.percent = percent
    discount.usage_limit = usage_limit
    discount.plan_ids = _plan_ids_str(plan_ids)
    discount.is_public = is_public
    await session.commit()
    await session.refresh(discount)
    return discount


async def set_discount_active(session: AsyncSession, discount_code_id: int, active: bool) -> DiscountCode | None:
    discount = await session.get(DiscountCode, discount_code_id)
    if discount is None:
        return None
    discount.is_active = active
    await session.commit()
    await session.refresh(discount)
    return discount


async def delete_discount_code(session: AsyncSession, discount_code_id: int) -> bool:
    discount = await session.get(DiscountCode, discount_code_id)
    if discount is None:
        return False
    await session.delete(discount)
    await session.commit()
    return True


async def get_discount_code(session: AsyncSession, discount_code_id: int) -> DiscountCode | None:
    return await session.get(DiscountCode, discount_code_id)


async def get_discount_code_by_name(session: AsyncSession, code: str) -> DiscountCode | None:
    result = await session.execute(select(DiscountCode).where(DiscountCode.code == normalize_discount_code(code)))
    return result.scalar_one_or_none()


async def list_discount_codes(session: AsyncSession) -> list[DiscountCode]:
    result = await session.execute(select(DiscountCode).order_by(DiscountCode.id))
    return list(result.scalars().all())


def _is_within_usage_limit(discount: DiscountCode) -> bool:
    return discount.usage_limit is None or discount.used_count < discount.usage_limit


def _applies_to_plan(discount: DiscountCode, plan_id: int) -> bool:
    return discount.plan_ids is None or str(plan_id) in discount.plan_ids.split(",")


async def validate_discount_code(session: AsyncSession, *, code: str, plan_id: int) -> DiscountCode:
    discount = await get_discount_code_by_name(session, code)
    if discount is None:
        raise DiscountCodeInvalidError("Discount code not found.")
    if not discount.is_active:
        raise DiscountCodeInvalidError("This discount code is no longer active.")
    if not _is_within_usage_limit(discount):
        raise DiscountCodeInvalidError("This discount code has reached its usage limit.")
    if not _applies_to_plan(discount, plan_id):
        raise DiscountCodeInvalidError("This discount code doesn't apply to the selected plan.")
    return discount


async def find_best_auto_discount(session: AsyncSession, plan_id: int) -> DiscountCode | None:
    """Highest-percent active, non-exhausted, PUBLIC code scoped to
    plan_id. Built now so the future Buy flow can call it; unused until
    then - see the admin panel spec §1/§7."""
    candidates = [
        d
        for d in await list_discount_codes(session)
        if d.is_active and d.is_public and _is_within_usage_limit(d) and _applies_to_plan(d, plan_id)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.percent)
