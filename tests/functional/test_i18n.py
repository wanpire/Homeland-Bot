from __future__ import annotations

import logging

import pytest


def test_t_returns_english_text() -> None:
    from app.i18n.texts import t

    assert t("menu_buy", "en") == "🔑 Buy Subscription"


def test_t_returns_persian_text() -> None:
    from app.i18n.texts import t

    assert t("menu_buy", "fa") == "🔑 خرید اشتراک"


def test_t_interpolates_kwargs() -> None:
    from app.i18n.texts import t

    result = t("price_duration", "en", days=30)
    assert result == "Duration: 30 days"


def test_t_falls_back_to_english_for_unknown_language(caplog: pytest.LogCaptureFixture) -> None:
    from app.i18n.texts import t

    with caplog.at_level(logging.WARNING):
        result = t("menu_buy", "de")
    assert result == "🔑 Buy Subscription"
    assert "de" in caplog.text


def test_t_missing_key_returns_bare_key(caplog: pytest.LogCaptureFixture) -> None:
    from app.i18n.texts import t

    with caplog.at_level(logging.WARNING):
        result = t("this_key_does_not_exist", "en")
    assert result == "this_key_does_not_exist"
    assert "this_key_does_not_exist" in caplog.text


def test_t_format_mismatch_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    from app.i18n.texts import t

    with caplog.at_level(logging.WARNING):
        result = t("price_duration", "en")  # missing required {days} kwarg
    assert result == "Duration: {days} days"


def test_texts_key_sets_match_exactly_between_languages() -> None:
    from app.i18n.texts import TEXTS

    assert set(TEXTS["en"].keys()) == set(TEXTS["fa"].keys())
    assert len(TEXTS["en"]) == 83


def test_texts_format_placeholders_match_between_languages() -> None:
    import re

    from app.i18n.texts import TEXTS

    placeholder_re = re.compile(r"\{(\w+)\}")
    for key, en_text in TEXTS["en"].items():
        en_placeholders = set(placeholder_re.findall(en_text))
        fa_placeholders = set(placeholder_re.findall(TEXTS["fa"][key]))
        assert en_placeholders == fa_placeholders, f"placeholder mismatch for key {key!r}"
