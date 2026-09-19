from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards.campaign import CAMPAIGN_SECTIONS, campaign_keyboard


def _only_button(markup: InlineKeyboardMarkup | None) -> InlineKeyboardButton:
    assert markup is not None
    rows = markup.inline_keyboard
    assert len(rows) == 1 and len(rows[0]) == 1
    return rows[0][0]


def test_no_button_returns_none() -> None:
    assert campaign_keyboard(None, "fa") is None


def test_menu_button_uses_main_menu_label_and_callback_per_language() -> None:
    fa = _only_button(campaign_keyboard({"kind": "menu", "key": "buy"}, "fa"))
    en = _only_button(campaign_keyboard({"kind": "menu", "key": "buy"}, "en"))
    assert fa.callback_data == en.callback_data == "menu:buy"
    assert fa.text == "🔑 خرید اشتراک"
    assert en.text == "🔑 Buy Subscription"


def test_custom_button_with_section_destination() -> None:
    btn = _only_button(
        campaign_keyboard({"kind": "custom", "label": "Go!", "dest": {"kind": "menu", "key": "renew"}}, "fa")
    )
    assert btn.text == "Go!" and btn.callback_data == "menu:renew" and btn.url is None


def test_custom_button_with_url_destination() -> None:
    btn = _only_button(
        campaign_keyboard({"kind": "custom", "label": "Site", "dest": {"kind": "url", "url": "https://x.y"}}, "en")
    )
    assert btn.text == "Site" and btn.url == "https://x.y" and btn.callback_data is None


def test_sections_exclude_language_and_tutorials() -> None:
    assert "language" not in CAMPAIGN_SECTIONS and "tutorials" not in CAMPAIGN_SECTIONS
