from __future__ import annotations

from pathlib import Path

_ADMIN_MODULES = (
    "admin.py",
    "admin_admins.py",
    "admin_block.py",
    "admin_discounts.py",
    "admin_renew.py",
    "admin_settings.py",
    "admin_fallback.py",
    "broadcast.py",
    "tutorial_admin.py",
)


def test_no_admin_facing_handler_imports_i18n() -> None:
    handlers_dir = Path(__file__).resolve().parents[2] / "app" / "bot" / "handlers"
    offenders = []
    for name in _ADMIN_MODULES:
        path = handlers_dir / name
        assert path.exists(), f"expected admin handler module not found: {path}"
        content = path.read_text()
        if "app.i18n" in content or "from app.i18n" in content:
            offenders.append(name)
    assert offenders == [], f"admin-facing modules must never import app.i18n: {offenders}"
