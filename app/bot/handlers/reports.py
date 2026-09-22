"""The Reports screen (epic part 4).

Every figure comes from app/services/reporting.py, the same module the
Financial screens use, so revenue here and revenue there are the same
number by construction rather than by coincidence."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.admin_fallback import NO_PERMISSION_TEXT
from app.bot.keyboards.reports import (
    backups_keyboard,
    health_keyboard,
    reports_menu_keyboard,
    reports_keyboard,
)
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.ibsng.client import IBSngClient
from app.config import get_settings
from app.services.backup import backup_history
from app.services.health import check_all
from app.services.logtopics import ensure_all_topics
from app.services.reporting import (
    DEFAULT_PERIOD,
    PERIODS,
    account_breakdown,
    revenue_summary,
    sales_report,
    signup_report,
    signup_count,
    top_plans,
    trial_conversion,
)
from app.services.server_health import check_server_health

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


_MENU_TEXT = "📊 <b>Reports</b>\n\nPick a report."


async def _require_sales(callback: CallbackQuery) -> bool:
    async with async_session_maker() as session:
        if await has_level(session, callback.from_user.id, "sales"):
            return True
    await callback.answer(NO_PERMISSION_TEXT, show_alert=True)
    return False


@router.callback_query(F.data == "adm:reports")
async def reports_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(_MENU_TEXT, reply_markup=reports_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("adm:reports:signups"))
async def reports_signups_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()
    period = _period_from(callback.data, index=3)

    async with async_session_maker() as session:
        report = await signup_report(session, period=period)

    label = PERIODS[period].label
    text = "\n".join([
        f"🆕 <b>Signups</b> — {label}",
        "",
        f"New users: <b>{report.signups}</b>",
        f"Of those, bought: {report.buyers}",
        f"Signup-to-paid: {report.conversion_rate}%",
        "",
        f"All-time users: {report.all_time}",
    ])
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=reports_keyboard(period, root="adm:reports:signups"))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:reports:sales"))
async def reports_sales_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()
    period = _period_from(callback.data, index=3)

    async with async_session_maker() as session:
        report = await sales_report(session, period=period)

    lines = [
        f"💰 <b>Sales</b> — {PERIODS[period].label}",
        "",
        f"Paid orders: <b>{report.orders}</b>",
        f"Revenue: <b>${report.revenue}</b>",
        f"Average order: ${report.average_order}",
        "",
        "<b>By plan</b>",
    ]
    if report.by_plan:
        for plan in report.by_plan:
            lines.append(f"• {html.escape(plan.plan_name)} — {plan.orders} · ${plan.revenue}")
    else:
        lines.append("No paid orders in this period.")
    if callback.message is not None:
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=reports_keyboard(period, root="adm:reports:sales")
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:reports:accounting"))
async def reports_accounting_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()
    period = _period_from(callback.data, index=3)

    async with async_session_maker() as session:
        summary = await revenue_summary(session, period=period)

    lines = [
        f"📊 <b>Accounting</b> — {PERIODS[period].label}",
        "",
        f"Revenue: <b>${summary.revenue}</b> from {summary.paid_orders} order(s)",
        f"Average order: ${summary.average_order}",
        f"Discounts given: ${summary.discounts_given}",
        "",
        "<b>By provider</b>",
    ]
    for name, totals in summary.by_provider.items():
        lines.append(
            f"• {name.title()}: {totals.orders} order(s) · ${totals.revenue}" if totals.orders
            else f"• {name.title()}: none"
        )
    lines += ["", "<b>By status</b>", " · ".join(f"{k} {v}" for k, v in sorted(summary.by_status.items())) or "none"]
    if callback.message is not None:
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=reports_keyboard(period, root="adm:reports:accounting")
        )
    await callback.answer()


@router.callback_query(F.data == "adm:reports:service")
async def reports_service_health_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """No period selector: this describes right now, not a window."""
    if not await _require_sales(callback):
        return
    await state.clear()

    results = await check_all()
    lines = ["🩺 <b>Service Health</b>", ""]
    for component, (healthy, detail) in results.items():
        mark = "💚" if healthy else "🔴"
        lines.append(f"{mark} {component}: {html.escape(detail)}")
    if callback.message is not None:
        await callback.message.edit_text("\n".join(lines), reply_markup=health_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm:reports:server")
async def reports_server_health_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()

    health = check_server_health()
    lines = [
        "🖥 <b>Server Health</b>",
        "",
        f"Disk: {health.disk_text}",
        f"Memory: {health.memory_text}",
        f"Load (1m): {health.load_text}",
        f"Bot uptime: {health.uptime_text}",
    ]
    if health.problems:
        lines += ["", "🟠 " + html.escape(", ".join(health.problems))]
    if callback.message is not None:
        await callback.message.edit_text("\n".join(lines), reply_markup=health_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm:reports:backups")
async def reports_backups_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()

    history = backup_history()
    lines = ["💾 <b>Backups</b>", ""]
    if history:
        lines.append(f"{len(history)} kept · newest {history[0].age_text} old")
        lines.append("")
        for entry in history[:10]:
            lines.append(f"• {html.escape(entry.name)} — {entry.size_text}, {entry.age_text} old")
    else:
        lines.append("No backups found yet. The nightly job runs at 03:00 UTC.")
    if callback.message is not None:
        await callback.message.edit_text("\n".join(lines), reply_markup=backups_keyboard())
    await callback.answer()


@router.message(Command("logtopics"))
async def logtopics_cmd(message: Message) -> None:
    """Creates any missing forum topic in the log group and reports what
    it found. Safe to re-run: existing topics are left alone."""
    if message.from_user is None:
        return
    async with async_session_maker() as session:
        if not await has_level(session, message.from_user.id, "full"):
            return

    chat_id = get_settings().admin_log_chat_id.strip()
    if not chat_id:
        await message.answer("⚠️ ADMIN_LOG_CHAT_ID is not set, so there is no log group to set up.")
        return

    outcomes = await ensure_all_topics(message.bot, int(chat_id))
    lines = ["📋 <b>Log group topics</b>", ""]
    lines += [f"• {name}: {outcome}" for name, outcome in outcomes.items()]
    await message.answer("\n".join(lines))


def _period_from(data: str, *, index: int) -> str:
    parts = data.split(":")
    candidate = parts[index] if len(parts) > index else ""
    return candidate if candidate in PERIODS else DEFAULT_PERIOD


@router.callback_query(F.data.startswith("adm:reports:overview"))
async def reports_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_sales(callback):
        return
    await state.clear()
    period = _period_from(callback.data, index=3)

    if callback.message is not None:
        await callback.message.edit_text(
            await _report_text(period), reply_markup=reports_keyboard(period, root="adm:reports:overview")
        )
    await callback.answer()
