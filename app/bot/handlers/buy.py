from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import (
    buy_category_keyboard,
    buy_plan_keyboard,
    buy_price_summary_keyboard,
    payment_link_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import CATEGORIES, category_display_name, format_data_cap, format_price_usd, get_plan, list_plans, plan_display_name
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.payments.nowpayments import NowPaymentsError, PaymentProviderNotConfiguredError
from app.services.payments.service import create_crypto_payment

logger = logging.getLogger(__name__)

router = Router(name="buy")

# Trial has its own dedicated flow (menu:trial) and must never be reachable
# through Buy — it's a real, $0.00 plan, not just an inactive one.
_BUY_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")


@router.callback_query(F.data == "menu:buy")
async def buy_start_cb(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        await callback.message.edit_text(t("buy_category_heading", lang), reply_markup=buy_category_keyboard(lang))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:category:"))
async def buy_category_cb(callback: CallbackQuery, lang: str) -> None:
    category = callback.data.split(":")[-1]
    if category not in _BUY_CATEGORIES:
        if callback.message is not None:
            await callback.message.edit_text(t("buy_category_heading", lang), reply_markup=buy_category_keyboard(lang))
        await callback.answer()
        return
    async with async_session_maker() as session:
        plans = await list_plans(session, category=category, active_only=True)
    if callback.message is not None:
        await callback.message.edit_text(t("buy_pick_plan", lang), reply_markup=buy_plan_keyboard(plans, lang))
    await callback.answer()


def _is_buyable(plan: Plan | None) -> bool:
    """Trial is a real, $0.00 plan — Buy must never expose it (that's menu:trial's job)."""
    return plan is not None and plan.category != "trial"


async def _price_summary_text(session: AsyncSession, plan: Plan, lang: str) -> str:
    lines = [
        f"🔑 <b>{plan_display_name(plan, lang)} ({category_display_name(plan.category, lang)})</b>",
        t("price_duration", lang, days=plan.duration_days),
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb)),
    ]
    discount = await find_best_auto_discount(session, plan.id)
    if discount is not None:
        discounted = discount_price(plan.price_usd, discount.percent)
        percent_text = f"{discount.percent.normalize():f}"
        lines.append(
            t("price_line_discounted", lang, original=format_price_usd(plan.price_usd), discounted=format_price_usd(discounted), percent=percent_text)
        )
    else:
        lines.append(t("price_line", lang, price=format_price_usd(plan.price_usd)))
    return "\n".join(lines)


@router.callback_query(F.data.startswith("buy:plan:"))
async def buy_plan_cb(callback: CallbackQuery, lang: str) -> None:
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            plan = None
        if plan is not None:
            text = await _price_summary_text(session, plan, lang)
    if plan is None:
        if callback.message is not None:
            await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=buy_price_summary_keyboard(plan.id, plan.category, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    plan_id = int(callback.data.split(":")[-1])
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="purchase", plan=plan, vpn_user=None,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error("NOWPayments invoice creation failed for plan %s", plan_id, exc_info=True)
            if callback.message is not None:
                await callback.message.edit_text(t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

    if callback.message is not None:
        await callback.message.edit_text(t("payment_link_heading", lang), reply_markup=payment_link_keyboard(payment.invoice_url, lang))
    await callback.answer()
