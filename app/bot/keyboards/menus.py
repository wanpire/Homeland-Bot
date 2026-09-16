"""Button-builder functions for the main menu and shared back controls.
Pure keyboard builders only - no handler logic here."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(*, is_admin: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    builder.button(text="🔑 Buy Subscription", callback_data="menu:buy", style="success")
    builder.button(text="♻️ Renew Service", callback_data="menu:renew", style="success")
    builder.button(text="🎁 Free Trial", callback_data="menu:trial", style="primary")
    builder.button(text="🛍 My Services", callback_data="menu:myservices", style="primary")
    builder.button(text="📚 Tutorials", callback_data="menu:tutorials", style="danger")
    builder.button(text="☎️ Support", callback_data="menu:support", style="danger")
    sizes += [2, 2, 2]

    if is_admin:
        builder.button(text="🛠 Admin Panel", callback_data="adm:root")
        sizes.append(1)

    builder.adjust(*sizes)
    return builder.as_markup()


def support_keyboard(url: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if url:
        builder.button(text="☎️ Contact Support", url=url)
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
