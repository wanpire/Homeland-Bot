"""The bidi-safe info line used by the Persian account screens."""

from __future__ import annotations

from app.i18n.bidi import FSI, PDI, RLM, info_line


def test_a_persian_line_is_pinned_rtl_with_the_value_isolated() -> None:
    line = info_line("رمز عبور", "<code>Ab12cd</code>", "fa")
    assert line == f"{RLM}رمز عبور: {FSI}<code>Ab12cd</code>{PDI}"


def test_the_marks_stay_outside_code_so_tap_to_copy_is_clean() -> None:
    line = info_line("نام کاربری", "<code>hl.d6jxur</code>", "fa")
    copied = line.split("<code>")[1].split("</code>")[0]
    assert copied == "hl.d6jxur"


def test_english_lines_carry_no_marks() -> None:
    assert info_line("Password", "<code>Ab12cd</code>", "en") == "Password: <code>Ab12cd</code>"
