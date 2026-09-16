from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import buy_category_keyboard, buy_plan_keyboard, buy_price_summary_keyboard
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.session import async_session_maker
from app.services.catalog import format_price_usd, get_plan, list_plans
from app.services.discounts import discount_price, find_best_auto_discount

router = Router(name="buy")

_CATEGORY_TEXT = "🔑 <b>Buy Subscription</b>\n\nPick a category:"
_TIER_TEXT = "Pick a plan:"


@router.callback_query(F.data == "menu:buy")
async def buy_start_cb(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(_CATEGORY_TEXT, reply_markup=buy_category_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("buy:category:"))
async def buy_category_cb(callback: CallbackQuery) -> None:
    category = callback.data.split(":")[-1]
    async with async_session_maker() as session:
        plans = await list_plans(session, category=category, active_only=True)
    if callback.message is not None:
        await callback.message.edit_text(_TIER_TEXT, reply_markup=buy_plan_keyboard(plans))
    await callback.answer()


_PLAN_GONE_TEXT = "⚠️ That plan no longer exists. Please pick another."
_COMING_SOON_TEXT = (
    "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
    "the moment they're live. No charge has been made and no account was created."
)


def _format_data_cap(data_cap_mb: int) -> str:
    if data_cap_mb % 1024 == 0:
        return f"{data_cap_mb // 1024} GB"
    return f"{data_cap_mb} MB"


async def _price_summary_text(session: AsyncSession, plan: Plan) -> str:
    lines = [
        f"🔑 <b>{plan.name} ({plan.category.title()})</b>",
        f"Duration: {plan.duration_days} days",
        f"Data: {_format_data_cap(plan.data_cap_mb)}",
    ]
    discount = await find_best_auto_discount(session, plan.id)
    if discount is not None:
        discounted = discount_price(plan.price_usd, discount.percent)
        lines.append(
            f"Price: <s>{format_price_usd(plan.price_usd)}</s> "
            f"{format_price_usd(discounted)} (-{discount.percent}%)"
        )
    else:
        lines.append(f"Price: {format_price_usd(plan.price_usd)}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("buy:plan:"))
async def buy_plan_cb(callback: CallbackQuery) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if plan is None:
            if callback.message is not None:
                await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
            await callback.answer()
            return
        text = await _price_summary_text(session, plan)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=buy_price_summary_keyboard(plan.id, plan.category))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text(_PLAN_GONE_TEXT, reply_markup=back_to_menu_keyboard())
        await callback.answer()
        return
    if callback.message is not None:
        await callback.message.edit_text(_COMING_SOON_TEXT, reply_markup=back_to_menu_keyboard())
    await callback.answer()
