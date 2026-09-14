"""Single source of truth for catalog seed data.

These constants are imported and used by:
- alembic/versions/0002_catalog.py (migration seed step)
- tests/conftest.py (re-seeding after truncation)
"""

from __future__ import annotations

SEED_GROUP_NAMES: tuple[str, ...] = ("HL-2W", "HL-1M", "HL-2M", "HL-3M")

# (name, duration_days, data_cap_mb, price_usd_str, group_name, sort_order)
SEED_PLANS: tuple[tuple[str, int, int, str, str, int], ...] = (
    ("2 Weeks", 14, 2048, "2.50", "HL-2W", 0),
    ("1 Month", 30, 5120, "5.00", "HL-1M", 1),
    ("2 Months", 60, 10240, "10.00", "HL-2M", 2),
    ("3 Months", 90, 102400, "30.00", "HL-3M", 3),
)
