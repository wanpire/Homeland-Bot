from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.buy import payment_link_keyboard
from app.bot.keyboards.menus import show_screen
from app.bot.keyboards.renew import (
    renew_category_keyboard,
    renew_empty_keyboard,
    renew_plan_keyboard,
    renew_price_summary_keyboard,
    renew_service_keyboard,
)
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.i18n.texts import t
from app.services.catalog import CATEGORIES, categories_with_active_plans, category_display_name, format_data_cap, format_price_usd, get_plan, list_plans, plan_display_name
from app.services.discounts import discount_price, find_best_auto_discount
from app.services.payments.plisio import PaymentProviderNotConfiguredError, PlisioError
from app.services.payments.service import create_crypto_payment
from app.services.vpn_users import get_owned_vpn_user, list_renewable_services

logger = logging.getLogger(__name__)

router = Router(name="renew")

# Trial has no renewal concept - it's excluded from every category/tier
# screen in this flow, same as Buy excludes it from its own.
_RENEW_CATEGORIES = tuple(category for category in CATEGORIES if category != "trial")

_MAX_POSTGRES_INT = 2**31 - 1


def _parse_int(raw: str) -> int | None:
    """Parses a callback_data id segment as a plain integer, with no
    upper bound check. Used where an out-of-range-but-well-formed id
    should still flow into its lookup so it degrades through that
    lookup's own not-found/gone screen, rather than the generic
    not-found screen used for a segment that isn't a number at all."""
    try:
        return int(raw)
    except ValueError:
        return None


def _in_postgres_int_range(value: int) -> bool:
    """VPNUser.id and Plan.id are both PostgreSQL `integer` (int4)
    columns - a numerically valid but out-of-range value (e.g.
    "2147483648") passes int() only to raise an unhandled
    asyncpg.DataError once bound to a query."""
    return 0 < value <= _MAX_POSTGRES_INT


def _parse_id(raw: str) -> int | None:
    """Parses a callback_data id segment, rejecting anything that isn't
    a well-formed, in-range id - used where any invalid id (malformed or
    out-of-range) should degrade to the same generic not-found screen,
    because an invalid id here means we don't even know which record is
    being referenced."""
    value = _parse_int(raw)
    if value is None or not _in_postgres_int_range(value):
        return None
    return value


async def _not_found(callback: CallbackQuery, lang: str) -> None:
    if callback.message is not None:
        await callback.message.edit_text(t("renew_not_found", lang), reply_markup=back_to_menu_keyboard(lang))
    await callback.answer()


async def _renew_categories(session: AsyncSession) -> set[str]:
    """Same trial-exclusion reasoning as Buy's own _buy_categories: trial
    is an active plan but has no renewal concept, so it never shows here."""
    active = await categories_with_active_plans(session)
    return {category for category in active if category in _RENEW_CATEGORIES}


async def _service_display_name(session: AsyncSession, vpn_user: VPNUser, lang: str) -> str:
    plan = await get_plan(session, vpn_user.plan_id) if vpn_user.plan_id is not None else None
    return plan_display_name(plan, lang) if plan is not None else vpn_user.ibsng_group


@router.callback_query(F.data == "menu:renew")
async def renew_start_cb(callback: CallbackQuery, lang: str) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        rows = await list_renewable_services(session, telegram_id)

    if not rows:
        if callback.message is not None:
            await show_screen(callback.message, t("renew_empty", lang), renew_empty_keyboard(lang))
        await callback.answer()
        return

    if callback.message is not None:
        await show_screen(callback.message, t("renew_list_heading", lang), renew_service_keyboard(rows, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:service:"))
async def renew_service_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return
        name = await _service_display_name(session, vpn_user, lang)
        active_categories = await _renew_categories(session)

    text = t("renew_pick_category", lang, name=name)
    if callback.message is not None:
        await callback.message.edit_text(
            text, reply_markup=renew_category_keyboard(vpn_user_id, lang, active_categories)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("renew:category:"))
async def renew_category_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return
        name = await _service_display_name(session, vpn_user, lang)

        category = parts[3] if len(parts) > 3 else ""
        if category not in _RENEW_CATEGORIES:
            active_categories = await _renew_categories(session)
            text = t("renew_pick_category", lang, name=name)
            if callback.message is not None:
                await callback.message.edit_text(
                    text, reply_markup=renew_category_keyboard(vpn_user_id, lang, active_categories)
                )
            await callback.answer()
            return

        plans = await list_plans(session, category=category, active_only=True)

    text = t("renew_pick_plan", lang, name=name)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=renew_plan_keyboard(plans, vpn_user_id, category, lang))
    await callback.answer()


def _is_renewable(plan: Plan | None) -> bool:
    """Trial is a real, $0.00 plan - Renew must never expose it, same
    reasoning as Buy's own _is_buyable."""
    return plan is not None and plan.category != "trial"


async def _renew_summary_text(session: AsyncSession, current_name: str, plan: Plan, lang: str) -> str:
    lines = [
        t("renew_summary_heading", lang, current=current_name, new=plan_display_name(plan, lang), category=category_display_name(plan.category, lang)),
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


@router.callback_query(F.data.startswith("renew:plan:"))
async def renew_plan_cb(callback: CallbackQuery, lang: str) -> None:
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    plan_id = _parse_int(parts[3]) if len(parts) > 3 else None
    if plan_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return

        plan = await get_plan(session, plan_id) if _in_postgres_int_range(plan_id) else None
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        current_name = await _service_display_name(session, vpn_user, lang)
        text = await _renew_summary_text(session, current_name, plan, lang)

    if callback.message is not None:
        await callback.message.edit_text(
            text, reply_markup=renew_price_summary_keyboard(vpn_user_id, plan.id, plan.category, lang)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("renew:confirm:"))
async def renew_confirm_cb(callback: CallbackQuery, lang: str) -> None:
    """Creates the Plisio invoice and hands over the link. Like Buy, no
    coin is chosen here - Plisio's invoice page handles that."""
    parts = callback.data.split(":")
    telegram_id = callback.from_user.id

    vpn_user_id = _parse_id(parts[2]) if len(parts) > 2 else None
    if vpn_user_id is None:
        await _not_found(callback, lang)
        return

    plan_id = _parse_int(parts[3]) if len(parts) > 3 else None
    if plan_id is None:
        await _not_found(callback, lang)
        return

    async with async_session_maker() as session:
        vpn_user = await get_owned_vpn_user(session, vpn_user_id, telegram_id)
        if vpn_user is None:
            await _not_found(callback, lang)
            return

        plan = await get_plan(session, plan_id) if _in_postgres_int_range(plan_id) else None
        if not _is_renewable(plan):
            if callback.message is not None:
                await callback.message.edit_text(t("plan_gone", lang), reply_markup=back_to_menu_keyboard(lang))
            await callback.answer()
            return

        try:
            payment = await create_crypto_payment(
                session, telegram_id=telegram_id, purpose="renew", plan=plan, vpn_user=vpn_user,
            )
        except PaymentProviderNotConfiguredError:
            if callback.message is not None:
                await callback.message.edit_text(
                    t("payment_coming_soon_renew", lang), reply_markup=back_to_menu_keyboard(lang)
                )
            await callback.answer()
            return
        except PlisioError:
            logger.error(
                "Plisio invoice creation failed for vpn_user %s plan %s", vpn_user_id, plan_id, exc_info=True,
            )
            if callback.message is not None:
                await callback.message.edit_text(
                    t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang)
                )
            await callback.answer()
            return

    # renew_and_change_group is deliberately never called here - no
    # renewal is executed until the callback (app/webhook.py) reports the
    # payment as completed.
    if callback.message is not None:
        await callback.message.edit_text(
            t("payment_link_heading", lang), reply_markup=payment_link_keyboard(payment.invoice_url, lang)
        )
    await callback.answer()
