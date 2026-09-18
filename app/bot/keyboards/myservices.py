from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.plan import Plan
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.i18n.texts import t

_STATUS_KEYS = {
    "active": "status_active",
    "expired": "status_expired",
    "pending": "status_pending",
    "unknown": "status_unknown",
}


def myservices_empty_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("menu_buy", lang), callback_data="menu:buy", style="success")
    builder.button(text=t("menu_trial", lang), callback_data="menu:trial", style="primary")
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_list_keyboard(rows: list[tuple[VPNUser, Plan | None, str]], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for vpn_user, plan, status in rows:
        name = plan.name if plan is not None else vpn_user.ibsng_group
        status_text = t(_STATUS_KEYS.get(status, "status_unknown"), lang)
        builder.button(
            text=f"{name} — {status_text}",
            callback_data=f"myservices:view:{vpn_user.id}",
        )
    builder.button(text=t("back_to_menu", lang), callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def myservices_detail_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("resend_setup_button", lang), callback_data=f"myservices:resend:{vpn_user_id}")
    builder.button(text=t("back_to_list_button", lang), callback_data="menu:myservices")
    builder.adjust(1)
    return builder.as_markup()


def myservices_protocol_keyboard(protocols: list[TutorialProtocol], vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"myservices:resend:{vpn_user_id}:protocol:{protocol.id}")
    builder.button(text=t("back_to_service_button", lang), callback_data=f"myservices:view:{vpn_user_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_platform_keyboard(
    platforms: list[TutorialPlatform], vpn_user_id: int, protocol_id: int, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(
            text=platform.label,
            callback_data=f"myservices:resend:{vpn_user_id}:platform:{protocol_id}:{platform.id}",
        )
    builder.button(text=t("back_button", lang), callback_data=f"myservices:resend:{vpn_user_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
