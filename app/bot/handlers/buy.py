from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.buy import buy_category_keyboard, buy_plan_keyboard
from app.db.session import async_session_maker
from app.services.catalog import list_plans

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
