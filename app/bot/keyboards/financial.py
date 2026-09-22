"""Keyboards for the Financial screens.

Period and filter state travels in the callback data rather than FSM, so
a keyboard an admin scrolls back to still means what it says instead of
silently applying whatever filter was set last."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.reporting import KNOWN_PROVIDERS, PERIODS, PaymentPage

_STATUS_FILTERS = (("all", "All"), ("paid", "Paid"), ("pending", "Pending"), ("failed", "Failed"))


def revenue_keyboard(active_period: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, period in PERIODS.items():
        label = f"• {period.label}" if key == active_period else period.label
        builder.button(text=label, callback_data=f"adm:fin:revenue:{key}")
    builder.button(text="⬅️ Back to Financial", callback_data="adm:fin")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def payments_keyboard(page: PaymentPage, *, status: str, provider: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    for row in page.rows:
        builder.button(
            text=f"#{row.id} ${row.amount_usd} {row.status} · {row.who}",
            callback_data=f"adm:fin:payment:{row.id}",
        )
        sizes.append(1)

    nav = 0
    if page.page > 0:
        builder.button(text="◀️ Prev", callback_data=f"adm:fin:payments:{status}:{provider}:{page.page - 1}")
        nav += 1
    if (page.page + 1) < page.pages:
        builder.button(text="Next ▶️", callback_data=f"adm:fin:payments:{status}:{provider}:{page.page + 1}")
        nav += 1
    if nav:
        sizes.append(nav)

    for key, label in _STATUS_FILTERS:
        text = f"• {label}" if key == status else label
        builder.button(text=text, callback_data=f"adm:fin:payments:{key}:{provider}:0")
    sizes.append(len(_STATUS_FILTERS))

    for name in ("all", *KNOWN_PROVIDERS):
        text = name.title() if name != "all" else "Any provider"
        builder.button(
            text=f"• {text}" if name == provider else text,
            callback_data=f"adm:fin:payments:{status}:{name}:0",
        )
    sizes.append(len(KNOWN_PROVIDERS) + 1)

    builder.button(text="🔍 Find by user", callback_data="adm:fin:payments:user")
    builder.button(text="⬅️ Back to Financial", callback_data="adm:fin")
    sizes += [1, 1]

    builder.adjust(*sizes)
    return builder.as_markup()


def payment_detail_keyboard(invoice_url: str | None, *, status: str, provider: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if invoice_url:
        builder.button(text="🔗 Invoice page", url=invoice_url)
    builder.button(text="⬅️ Back to Payments", callback_data=f"adm:fin:payments:{status}:{provider}:0")
    builder.adjust(1)
    return builder.as_markup()


def payments_search_keyboard(*, status: str, provider: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data=f"adm:fin:payments:{status}:{provider}:0")
    builder.adjust(1)
    return builder.as_markup()
