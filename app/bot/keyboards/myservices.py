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


def myservices_root_keyboard(lang: str) -> InlineKeyboardMarkup:
    """My Services' entry screen. "Add new account" is the Buy flow's own
    entry callback, so buying from here is the same flow as from the main
    menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("myservices_list_button", lang), callback_data="myservices:list")
    builder.button(text=t("myservices_add_button", lang), callback_data="menu:buy")
    builder.button(text=t("back_to_menu_short", lang), callback_data="menu:root", style="danger")
    builder.adjust(1)
    return builder.as_markup()


def myservices_empty_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("menu_buy", lang), callback_data="menu:buy", style="success")
    builder.button(text=t("menu_trial", lang), callback_data="menu:trial", style="primary")
    builder.button(text=t("back_plain", lang), callback_data="menu:myservices")
    builder.adjust(2, 1)
    return builder.as_markup()


def myservices_list_keyboard(rows: list[tuple[VPNUser, Plan | None, str]], lang: str) -> InlineKeyboardMarkup:
    """One button per account, labelled by its username: unique per
    account, where plan names repeat (several trials used to read
    identically)."""
    builder = InlineKeyboardBuilder()
    for vpn_user, _plan, status in rows:
        status_text = t(_STATUS_KEYS.get(status, "status_unknown"), lang)
        builder.button(
            text=f"{vpn_user.ibsng_username} — {status_text}",
            callback_data=f"myservices:view:{vpn_user.id}",
        )
    builder.button(text=t("back_plain", lang), callback_data="menu:myservices")
    builder.adjust(1)
    return builder.as_markup()


def account_menu_keyboard(vpn_user_id: int, *, is_trial: bool, lang: str) -> InlineKeyboardMarkup:
    """AloBot's account action menu: actions two per row, then Back (to the
    list) and Back to menu on their own rows. A trial has no paid plan to
    renew, so it gets no renew button."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("account_info_button", lang), callback_data=f"myservices:detail:{vpn_user_id}")
    actions = 1
    if not is_trial:
        builder.button(text=t("account_renew_button", lang), callback_data=f"renew:service:{vpn_user_id}")
        actions += 1
    builder.button(text=t("account_password_button", lang), callback_data=f"myservices:pw:{vpn_user_id}")
    builder.button(text=t("account_ownership_button", lang), callback_data=f"myservices:xfer:{vpn_user_id}")
    actions += 2
    builder.button(text=t("back_plain", lang), callback_data="myservices:list", style="primary")
    builder.button(text=t("back_to_menu_short", lang), callback_data="menu:root", style="danger")
    builder.adjust(*([2] * (actions // 2) + [1] * (actions % 2)), 1, 1)
    return builder.as_markup()


def back_to_account_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("back_plain", lang), callback_data=f"myservices:view:{vpn_user_id}", style="primary")
    return builder.as_markup()


def myservices_detail_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    """Under the account-info screen: Resend Setup, and Back to the
    account's menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("resend_setup_button", lang), callback_data=f"myservices:resend:{vpn_user_id}")
    builder.button(text=t("back_plain", lang), callback_data=f"myservices:view:{vpn_user_id}", style="primary")
    builder.adjust(1)
    return builder.as_markup()


def password_confirm_keyboard(vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("pw_confirm_button", lang), callback_data=f"myservices:pwdo:{vpn_user_id}", style="success")
    builder.button(text=t("back_plain", lang), callback_data=f"myservices:view:{vpn_user_id}", style="primary")
    builder.adjust(1)
    return builder.as_markup()


def myservices_protocol_keyboard(protocols: list[TutorialProtocol], vpn_user_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"myservices:resend:{vpn_user_id}:protocol:{protocol.id}")
    builder.button(text=t("back_to_service_button", lang), callback_data=f"myservices:detail:{vpn_user_id}")
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
