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
from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import CATEGORIES, categories_with_active_plans, category_display_name, format_data_cap, format_price_usd, get_plan, list_plans, plan_display_name
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.payments.nowpayments import NowPaymentsError, PaymentBelowMinimumError, PaymentProviderNotConfiguredError
from app.bot.handlers._payability import render_payability
from app.services.payments.currencies import find_currency
from app.services.payments.minimums import invalidate
from app.services.payments.service import check_payability, create_crypto_payment, quote_amount

logger = logging.getLogger(__name__)

router = Router(name="buy")

# Trial has its own dedicated flow (menu:trial) and must never be reachable
# through Buy — it's a real, $0.00 plan, not just an inactive one.
_BUY_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")


async def _buy_categories(session: AsyncSession) -> set[str]:
    """Trial is filtered out here, not in the keyboard: it's a real,
    active plan, so categories_with_active_plans reports it - but Buy
    must never expose it (that's menu:trial's job)."""
    active = await categories_with_active_plans(session)
    return {category for category in active if category in _BUY_CATEGORIES}


@router.callback_query(F.data == "menu:buy")
async def buy_start_cb(callback: CallbackQuery, lang: str) -> None:
    async with async_session_maker() as session:
        active_categories = await _buy_categories(session)
    if callback.message is not None:
        await show_screen(
            callback.message, t("buy_category_heading", lang), buy_category_keyboard(lang, active_categories)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:category:"))
async def buy_category_cb(callback: CallbackQuery, lang: str) -> None:
    category = callback.data.split(":")[-1]
    if category not in _BUY_CATEGORIES:
        async with async_session_maker() as session:
            active_categories = await _buy_categories(session)
        if callback.message is not None:
            await callback.message.edit_text(
                t("buy_category_heading", lang), reply_markup=buy_category_keyboard(lang, active_categories)
            )
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
        t("price_data", lang, cap=format_data_cap(plan.data_cap_mb, lang)),
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
    """No invoice is created here any more. NOWPayments enforces a
    per-coin minimum that moves with network fees, so this step asks
    which coins can pay this exact amount right now and offers only
    those - a buyer can no longer pick a coin on the hosted page and
    dead-end on "the network minimum is higher than the price"."""
    plan_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        amount, _ = await quote_amount(session, plan)
        category = plan.category

    try:
        report = await check_payability(amount)
    except PaymentProviderNotConfiguredError:
        if callback.message is not None:
            await callback.message.edit_text(t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang))
        await callback.answer()
        return

    await render_payability(
        callback,
        report,
        amount,
        lang,
        pay_prefix=f"buy:pay:{plan_id}",
        back_to_summary_cb=f"buy:plan:{plan_id}",
        back_to_plans_cb=f"buy:category:{category}",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:pay:"))
async def buy_pay_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    try:
        plan_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    code = parts[3]
    telegram_id = callback.from_user.id

    async with async_session_maker() as session:
        plan = await get_plan(session, plan_id)
        if not _is_buyable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return
        amount, _ = await quote_amount(session, plan)
        category = plan.category

        try:
            report = await check_payability(amount)
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(
                    t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang)
                )
            await callback.answer()
            return

        # A stale keyboard, a coin dropped from Settings, or a minimum
        # that moved since the chooser rendered: re-offer whatever is
        # payable now rather than invoicing something that can't be paid.
        currency = find_currency(code)
        if currency is None or currency.code not in {c.code for c in report.payable}:
            await render_payability(
                callback,
                report,
                amount,
                lang,
                pay_prefix=f"buy:pay:{plan_id}",
                back_to_summary_cb=f"buy:plan:{plan_id}",
                back_to_plans_cb=f"buy:category:{category}",
                notice=t("payment_currency_changed", lang),
            )
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session,
                telegram_id=telegram_id,
                purpose="purchase",
                plan=plan,
                vpn_user=None,
                pay_currency=currency.code,
            )
        except PaymentBelowMinimumError:
            # NOWPayments disagreed with our cached minimum. Drop that
            # coin's entry so the next lookup re-fetches, then let the
            # buyer choose again instead of dead-ending them.
            logger.warning("NOWPayments rejected %s as below minimum for plan %s", currency.code, plan_id)
            await invalidate(currency.code)
            refreshed = await check_payability(amount)
            await render_payability(
                callback,
                refreshed,
                amount,
                lang,
                pay_prefix=f"buy:pay:{plan_id}",
                back_to_summary_cb=f"buy:plan:{plan_id}",
                back_to_plans_cb=f"buy:category:{category}",
                notice=t("payment_currency_changed", lang),
            )
            await callback.answer()
            return
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(
                    t("payment_coming_soon", lang), reply_markup=back_to_menu_keyboard(lang)
                )
            await callback.answer()
            return
        except NowPaymentsError:
            logger.error(
                "NOWPayments invoice creation failed for plan %s in %s", plan_id, currency.code, exc_info=True
            )
            if callback.message is not None:
                await callback.message.edit_text(
                    t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang)
                )
            await callback.answer()
            return

    if callback.message is not None:
        await callback.message.edit_text(
            t("payment_link_heading", lang), reply_markup=payment_link_keyboard(payment.invoice_url, lang)
        )
    await callback.answer()
