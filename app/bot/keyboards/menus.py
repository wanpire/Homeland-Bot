"""Button-builder functions for the main menu and shared back controls.
Pure keyboard builders only - no handler logic here."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


def main_menu(*, is_admin: bool, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes: list[int] = []

    builder.button(text=t("menu_buy", lang), callback_data="menu:buy", style="success")
    builder.button(text=t("menu_renew", lang), callback_data="menu:renew", style="success")
    builder.button(text=t("menu_trial", lang), callback_data="menu:trial", style="primary")
    builder.button(text=t("menu_myservices", lang), callback_data="menu:myservices", style="primary")
    builder.button(text=t("menu_tutorials", lang), callback_data="menu:tutorials", style="danger")
    builder.button(text=t("menu_support", lang), callback_data="menu:support", style="danger")
    builder.button(text=t("menu_language", lang), callback_data="menu:language")
    sizes += [2, 2, 2, 1]

    if is_admin:
        builder.button(text="🛠 Admin Panel", callback_data="adm:root")
        sizes.append(1)

    builder.adjust(*sizes)
    return builder.as_markup()


def support_keyboard(url: str | None, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if url:
        builder.button(text=t("contact_support_button", lang), url=url)
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()
