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
    assert len(TEXTS["en"]) == 94


def test_texts_format_placeholders_match_between_languages() -> None:
    import re

    from app.i18n.texts import TEXTS

    placeholder_re = re.compile(r"\{(\w+)\}")
    for key, en_text in TEXTS["en"].items():
        en_placeholders = set(placeholder_re.findall(en_text))
        fa_placeholders = set(placeholder_re.findall(TEXTS["fa"][key]))
        assert en_placeholders == fa_placeholders, f"placeholder mismatch for key {key!r}"


def test_t_falls_back_to_english_when_key_missing_from_requested_language(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: a key present in English but missing from Persian should
    fall back to English text (with a logged warning), not return the bare key."""
    from app.i18n import texts
    from app.i18n.texts import t

    # Monkeypatch: add a key to English only
    original_en = texts.TEXTS["en"].copy()
    original_fa = texts.TEXTS["fa"].copy()
    texts.TEXTS["en"]["test_asymmetric_key"] = "This is English only"
    # fa dict intentionally does NOT have this key

    try:
        with caplog.at_level(logging.WARNING):
            result = t("test_asymmetric_key", "fa")
        # Should fall back to English text, not return the bare key
        assert result == "This is English only"
        # Should log a warning about the missing key
        assert "test_asymmetric_key" in caplog.text
        assert "fa" in caplog.text
    finally:
        # Restore original dicts
        texts.TEXTS["en"] = original_en
        texts.TEXTS["fa"] = original_fa
