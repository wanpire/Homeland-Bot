"""Keyboards for the admin Ad Campaign flow (admin screens, English-only)
and the one customer-facing piece: the single button rendered under each
delivered campaign message (campaign_keyboard, bilingual via t())."""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n.texts import t

# Main-menu sections a campaign button may point at. Each key maps to the
# main menu's own callback data ("menu:<key>") and label ("menu_<key>"),
# so tapping a campaign button lands exactly where the main menu's button
# does. Language is deliberately absent - it is not a campaign
# destination. Tutorials was absent while it was a coming-soon
# placeholder and joined the list when the real section shipped.
CAMPAIGN_SECTIONS: tuple[str, ...] = ("buy", "renew", "trial", "myservices", "tutorials", "support")

# Admin-facing section names for the chooser screens.
SECTION_ADMIN_LABELS: dict[str, str] = {
    "buy": "🔑 Buy Subscription",
    "renew": "♻️ Renew Service",
    "trial": "🎁 Free Trial",
    "myservices": "🛍 My Services",
    "tutorials": "📚 Tutorials",
    "support": "☎️ Support",
}

Button = dict[str, Any] | None

CANCEL_CB = "adm:broadcast:cancel"
BACK_TO_BUTTON_CB = "adm:broadcast:campaign:btn"
CUSTOM_CB = "adm:broadcast:campaign:btn:custom"
CONFIRM_CB = "adm:broadcast:campaign:confirm"


def campaign_keyboard(button: Button, lang: str) -> InlineKeyboardMarkup | None:
    """The keyboard delivered to one recipient. None when the campaign has
    no button. A "menu" button renders the main menu's own label in the
    recipient's language; a "custom" button uses the admin's label
    verbatim for everyone."""
    if button is None:
        return None
    builder = InlineKeyboardBuilder()
    if button["kind"] == "menu":
        key = button["key"]
        builder.button(text=t(f"menu_{key}", lang), callback_data=f"menu:{key}")
    else:
        dest = button["dest"]
        if dest["kind"] == "url":
            builder.button(text=button["label"], url=dest["url"])
        else:
            builder.button(text=button["label"], callback_data=f"menu:{dest['key']}")
    builder.adjust(1)
    return builder.as_markup()


def _cancel_row(builder: InlineKeyboardBuilder) -> None:
    builder.button(text="❌ Cancel", callback_data=CANCEL_CB)


def campaign_content_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="adm:broadcast")
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_button_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Buy Subscription (preset)", callback_data="adm:broadcast:campaign:btn:preset")
    builder.button(text="📋 Other main-menu button", callback_data="adm:broadcast:campaign:btn:menu")
    builder.button(text="✏️ Custom button", callback_data=CUSTOM_CB)
    builder.button(text="➡️ No button", callback_data="adm:broadcast:campaign:btn:none")
    builder.button(text="⬅️ Back", callback_data="adm:broadcast:campaign")
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_section_keyboard(prefix: str, *, exclude: tuple[str, ...] = ()) -> InlineKeyboardMarkup:
    """One row per section, callback f"{prefix}:{key}". Used for "other
    main-menu button" (prefix adm:broadcast:campaign:btn:menu, excluding
    buy since that is the preset)."""
    builder = InlineKeyboardBuilder()
    for key in CAMPAIGN_SECTIONS:
        if key in exclude:
            continue
        builder.button(text=SECTION_ADMIN_LABELS[key], callback_data=f"{prefix}:{key}")
    builder.button(text="⬅️ Back", callback_data=BACK_TO_BUTTON_CB)
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_custom_dest_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key in CAMPAIGN_SECTIONS:
        builder.button(text=SECTION_ADMIN_LABELS[key], callback_data=f"adm:broadcast:campaign:dest:{key}")
    builder.button(text="🔗 URL", callback_data="adm:broadcast:campaign:dest:url")
    builder.button(text="⬅️ Back", callback_data=CUSTOM_CB)
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_back_cancel_keyboard(back_cb: str) -> InlineKeyboardMarkup:
    """For the two text-input steps (custom label, URL)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data=back_cb)
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()


def campaign_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Send", callback_data=CONFIRM_CB, style="success")
    builder.button(text="⬅️ Back", callback_data=BACK_TO_BUTTON_CB)
    _cancel_row(builder)
    builder.adjust(1)
    return builder.as_markup()
