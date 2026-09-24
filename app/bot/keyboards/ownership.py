"""Keyboards for My Services' Change Ownership flow (app/bot/handlers/ownership.py)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t


def transfer_confirm_keyboard(vpn_user_id: int, recipient_telegram_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("xfer_send_button", lang),
        callback_data=f"myservices:xferask:{vpn_user_id}:{recipient_telegram_id}",
        style="success",
    )
    builder.button(text=t("back_plain", lang), callback_data=f"myservices:view:{vpn_user_id}", style="primary")
    builder.adjust(1)
    return builder.as_markup()


def transfer_pending_keyboard(transfer_id: int, vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("xfer_cancel_button", lang), callback_data=f"xfer:cancel:{transfer_id}", style="danger")
    builder.button(text=t("back_plain", lang), callback_data=f"myservices:view:{vpn_user_id}", style="primary")
    builder.adjust(1)
    return builder.as_markup()


def transfer_offer_keyboard(transfer_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("xfer_accept_button", lang), callback_data=f"xfer:accept:{transfer_id}", style="success")
    builder.button(text=t("xfer_decline_button", lang), callback_data=f"xfer:decline:{transfer_id}", style="danger")
    builder.adjust(2)
    return builder.as_markup()


def to_my_services_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("menu_myservices", lang), callback_data="myservices:list")
    return builder.as_markup()
