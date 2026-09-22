"""Financial screens: revenue overview, payment search, payment detail.

Read-only. Period and filter state travels in callback data rather than
FSM, so an admin scrolling back to an older keyboard sees exactly what
it says. The one FSM state here holds a free-text user search while it
is being typed and is cleared the moment it resolves."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.admin_fallback import NO_PERMISSION_TEXT
from app.bot.keyboards.financial import (
    payment_detail_keyboard,
    payments_keyboard,
    payments_search_keyboard,
    revenue_keyboard,
)
from app.bot.states.financial import PaymentSearchStates
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.reporting import (
    DEFAULT_PERIOD,
    PERIODS,
    payment_detail,
    payment_page,
    resolve_user_query,
    revenue_summary,
)

logger = logging.getLogger(__name__)

router = Router(name="financial")

_SEARCH_PROMPT = (
    "🔍 <b>Find payments by user</b>\n\n"
    "Send a Telegram ID or a @username."
)
_NO_SUCH_USER = "⚠️ No user matches that. Send a Telegram ID or a @username, or cancel."


async def _require_sales(callback: CallbackQuery) -> bool:
    """Refusals are spoken aloud: this router consumes the callback, so
    admin_fallback never gets the chance to show its alert."""
    async with async_session_maker() as session:
        if await has_level(session, callback.from_user.id, "sales"):
            return True
    await callback.answer(NO_PERMISSION_TEXT, show_alert=True)
    return False


def _revenue_text(summary) -> str:  # type: ignore[no-untyped-def]
    period_label = PERIODS.get(summary.period, PERIODS[DEFAULT_PERIOD]).label
    lines = [
        f"📈 <b>Revenue Overview</b> — {period_label}",
        "",
        f"Paid orders: <b>{summary.paid_orders}</b>",
        f"Revenue: <b>${summary.revenue}</b>",
        f"Average order: ${summary.average_order}",
        f"Discounts given: ${summary.discounts_given}",
        "",
        "<b>By provider</b>",
    ]
    for name, totals in summary.by_provider.items():
        if totals.orders:
            lines.append(f"• {name.title()}: {totals.orders} order(s) · ${totals.revenue}")
        else:
            lines.append(f"• {name.title()}: none yet")

    lines += ["", "<b>By status</b>"]
    if summary.by_status:
        lines.append(" · ".join(f"{status} {count}" for status, count in sorted(summary.by_status.items())))
    else:
        lines.append("No payments in this period.")
    return "\n".join(lines)


@router.callback_query(F.data == "adm:fin:revenue")
@router.callback_query(F.data.startswith("adm:fin:revenue:"))
async def revenue_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()

    parts = callback.data.split(":")
    period = parts[3] if len(parts) > 3 and parts[3] in PERIODS else DEFAULT_PERIOD

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period=period)

    if callback.message is not None:
        await callback.message.edit_text(_revenue_text(summary), reply_markup=revenue_keyboard(period))
    await callback.answer()


def _payments_text(page, *, status: str, provider: str, telegram_id: int | None) -> str:  # type: ignore[no-untyped-def]
    scope = [f"status: {status}", f"provider: {provider}"]
    if telegram_id is not None:
        scope.append(f"user: {telegram_id}")
    header = f"🧾 <b>Payments</b> — {' · '.join(scope)}"
    if not page.rows:
        return f"{header}\n\nNo payments match."
    return f"{header}\nPage {page.page + 1}/{page.pages} · {page.total} total"


async def _render_payments(
    callback: CallbackQuery, *, status: str, provider: str, page_number: int, telegram_id: int | None = None
) -> None:
    async with async_session_maker() as session:
        page = await payment_page(
            session,
            status=None if status == "all" else status,
            provider=None if provider == "all" else provider,
            telegram_id=telegram_id,
            page=page_number,
        )
    if callback.message is not None:
        await callback.message.edit_text(
            _payments_text(page, status=status, provider=provider, telegram_id=telegram_id),
            reply_markup=payments_keyboard(page, status=status, provider=provider),
        )


@router.callback_query(F.data == "adm:fin:payments")
async def payments_entry_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()
    await _render_payments(callback, status="all", provider="all", page_number=0)
    await callback.answer()


@router.callback_query(F.data == "adm:fin:payments:user")
async def payments_search_prompt_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.set_state(PaymentSearchStates.query)
    if callback.message is not None:
        await callback.message.edit_text(
            _SEARCH_PROMPT, reply_markup=payments_search_keyboard(status="all", provider="all")
        )
    await callback.answer()


@router.message(PaymentSearchStates.query)
async def payments_search_msg(message: Message, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, message.from_user.id, "sales"):
            await state.clear()
            return
        telegram_id = await resolve_user_query(session, message.text or "")

    if telegram_id is None:
        await message.answer(_NO_SUCH_USER, reply_markup=payments_search_keyboard(status="all", provider="all"))
        return

    await state.clear()
    async with async_session_maker() as session:
        page = await payment_page(session, status=None, provider=None, telegram_id=telegram_id, page=0)
    await message.answer(
        _payments_text(page, status="all", provider="all", telegram_id=telegram_id),
        reply_markup=payments_keyboard(page, status="all", provider="all"),
    )


@router.callback_query(F.data.startswith("adm:fin:payments:"))
async def payments_filtered_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()

    parts = callback.data.split(":")
    status = parts[3] if len(parts) > 3 else "all"
    provider = parts[4] if len(parts) > 4 else "all"
    try:
        page_number = int(parts[5]) if len(parts) > 5 else 0
    except ValueError:
        page_number = 0

    await _render_payments(callback, status=status, provider=provider, page_number=page_number)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:fin:payment:"))
async def payment_detail_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()

    try:
        payment_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    async with async_session_maker() as session:
        detail = await payment_detail(session, payment_id)

    if detail is None:
        await callback.answer("⚠️ That payment no longer exists.", show_alert=True)
        return

    payment = detail.payment
    who = f"@{detail.username}" if detail.username else str(payment.telegram_id)
    lines = [
        f"🧾 <b>Payment #{payment.id}</b>",
        "",
        f"Buyer: {html.escape(who)} (<code>{payment.telegram_id}</code>)",
        f"Plan: {html.escape(detail.plan_name or payment.group_name)}",
        f"Purpose: {payment.purpose}",
        f"Amount: <b>${payment.amount_usd}</b>",
    ]
    if payment.original_amount_usd is not None:
        lines.append(f"Original: ${payment.original_amount_usd} (discount applied)")
    lines += [
        f"Status: <b>{payment.status}</b>",
        f"Provider: {payment.provider}",
    ]
    if payment.provider_payment_id:
        lines.append(f"Provider ID: <code>{html.escape(payment.provider_payment_id)}</code>")
    if payment.ibsng_username:
        lines.append(f"Account: <code>{html.escape(payment.ibsng_username)}</code>")
    lines.append(f"Created: {payment.created_at:%Y-%m-%d %H:%M} UTC")
    if payment.resolved_at is not None:
        lines.append(f"Resolved: {payment.resolved_at:%Y-%m-%d %H:%M} UTC")

    if callback.message is not None:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=payment_detail_keyboard(payment.invoice_url, status="all", provider="all"),
        )
    await callback.answer()
