"""The Reports screen (epic part 4).

Every figure comes from app/services/reporting.py, the same module the
Financial screens use, so revenue here and revenue there are the same
number by construction rather than by coincidence."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.handlers.admin_fallback import NO_PERMISSION_TEXT
from app.bot.keyboards.reports import reports_keyboard
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.ibsng.client import IBSngClient
from app.services.reporting import (
    DEFAULT_PERIOD,
    PERIODS,
    account_breakdown,
    revenue_summary,
    signup_count,
    top_plans,
    trial_conversion,
)

logger = logging.getLogger(__name__)

router = Router(name="reports")

_STATUS_ORDER = ("active", "expired", "pending", "unknown")


async def _report_text(period: str) -> str:
    async with async_session_maker() as session:
        signups, signups_all = await signup_count(session, period=period)
        revenue = await revenue_summary(session, period=period)
        conversion = await trial_conversion(session, period=period)
        plans = await top_plans(session, period=period)

    async with async_session_maker() as session, IBSngClient() as client:
        accounts = await account_breakdown(session, client)

    label = PERIODS.get(period, PERIODS[DEFAULT_PERIOD]).label
    lines = [
        f"📊 <b>Reports</b> — {label}",
        "",
        f"Signups: <b>{signups}</b> (all time: {signups_all})",
        f"Revenue: <b>${revenue.revenue}</b> from {revenue.paid_orders} paid order(s)",
        "",
        "<b>Accounts</b>",
    ]

    if accounts.total:
        tally = " · ".join(
            f"{status} {accounts.counts.get(status, 0)}"
            for status in _STATUS_ORDER
            if accounts.counts.get(status)
        )
        lines.append(tally or "No status reported.")
        if accounts.sampled:
            # Said out loud: a report that silently sampled would be
            # worse than one that admits it.
            lines.append(f"(live status of the {accounts.checked} newest of {accounts.total} accounts)")
    else:
        lines.append("No accounts yet.")

    lines += [
        "",
        "<b>Trial conversion</b>",
        f"Trials started: {conversion.trials} · went on to pay: {conversion.converted} → {conversion.rate}%",
        "",
        "<b>Top plans</b> (paid orders in period)",
    ]
    if plans:
        for index, plan in enumerate(plans, start=1):
            lines.append(
                f"{index}. {html.escape(plan.plan_name)} ({html.escape(plan.category)})"
                f" — {plan.orders} · ${plan.revenue}"
            )
    else:
        lines.append("No paid orders in this period.")

    return "\n".join(lines)


@router.callback_query(F.data == "adm:reports")
@router.callback_query(F.data.startswith("adm:reports:"))
async def reports_cb(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as session:
        if not await has_level(session, callback.from_user.id, "sales"):
            # Spoken aloud: this handler consumes the callback, so
            # admin_fallback never gets to show its alert.
            await callback.answer(NO_PERMISSION_TEXT, show_alert=True)
            return
    await state.clear()

    parts = callback.data.split(":")
    period = parts[2] if len(parts) > 2 and parts[2] in PERIODS else DEFAULT_PERIOD

    if callback.message is not None:
        await callback.message.edit_text(await _report_text(period), reply_markup=reports_keyboard(period))
    await callback.answer()
