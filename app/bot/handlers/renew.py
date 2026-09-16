from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import CATEGORIES, get_plan, list_plans
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services

router = Router(name="renew")

_LIST_TEXT = "♻️ <b>Renew Service</b>\n\nWhich service do you want to renew?"
_EMPTY_TEXT = "♻️ <b>Renew Service</b>\n\nYou don't have any services to renew yet."
_NOT_FOUND_TEXT = "⚠️ Service not found."
_TIER_TEXT = "Pick a plan:"

# Trial has no renewal concept - it's excluded from every category/tier
# screen in this flow, same as Buy excludes it from its own.
_RENEW_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")


async def _not_found(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.edit_text(_NOT_FOUND_TEXT, reply_markup=back_to_menu_keyboard())
    await callback.answer()


async def _service_display_name(session: AsyncSession, vpn_user: VPNUser) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    return plan.name if plan is not None else vpn_user.ibsng_group


@router.callback_query(F.data == "menu:renew")
async def renew_start_cb(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        rows = await list_renewable_services(session, telegram_id)

    if not rows:
        if callback.message is not None:
            await callback.message.edit_text(_EMPTY_TEXT, reply_markup=renew_empty_keyboard())
        await callback.answer()
        return

    if callback.message is not None:
        await callback.message.edit_text(_LIST_TEXT, reply_markup=renew_service_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:service:"))
async def renew_service_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    try:
        vpn_user_id = int(parts[2])
    except (IndexError, ValueError):
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return
        name = await _service_display_name(session, vpn_user)

    text = f"♻️ <b>Renew {name}</b>\n\nPick a category:"
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=renew_category_keyboard(vpn_user_id))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:category:"))
async def renew_category_cb(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    try:
        vpn_user_id = int(parts[2])
    except (IndexError, ValueError):
        await _not_found(callback)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback)
            return
        name = await _service_display_name(session, vpn_user)

        category = parts[3] if len(parts) > 3 else ""
        if category not in _RENEW_CATEGORIES:
            text = f"♻️ <b>Renew {name}</b>\n\nPick a category:"
            if callback.message is not None:
                await callback.message.edit_text(text, reply_markup=renew_category_keyboard(vpn_user_id))
            await callback.answer()
            return

        plans = await list_plans(session, category=category, active_only=True)

    if callback.message is not None:
        await callback.message.edit_text(_TIER_TEXT, reply_markup=renew_plan_keyboard(plans, vpn_user_id, category))
    await callback.answer()
