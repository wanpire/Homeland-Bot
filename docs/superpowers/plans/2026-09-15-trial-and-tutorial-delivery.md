# Free Trial & Tutorial/Profile Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Free Trial flow (one 24h/1GB trial account per Telegram user, lifetime) and the tutorial/OpenVPN-profile delivery infrastructure it depends on, plus a minimal admin flow to upload real content into that infrastructure.

**Architecture:** Two new small service modules (`vpn_users.py` for credential generation + IBSng account creation, `tutorials.py` + `tutorial_delivery.py` for guide/profile storage and delivery) sit on top of the existing catalog/IBSngClient foundation from the bootstrap slice. A stateless (no-FSM) callback flow drives the trial screens, matching the existing `users.py` pattern; a small FSM-based flow drives admin content upload, since that genuinely needs multi-step "pick options then send me a file" state.

**Tech Stack:** Python 3.12, aiogram 3.x (FSM via `aiogram.fsm`), SQLAlchemy 2.0 async, Alembic, pytest + pytest-asyncio (existing test harness: fake IBSng server, fake bot session, `dispatcher`/`seeded_catalog` fixtures).

**Spec:** `docs/superpowers/specs/2026-09-15-trial-and-tutorial-delivery-design.md` (and its parent, `docs/superpowers/specs/2026-09-14-homeland-bot-design.md`, for project-wide conventions)

## Global Constraints

- Python 3.12+, aiogram >=3.4,<4, SQLAlchemy >=2.0,<3.
- Async only — no blocking I/O in handlers or services.
- Type hints on every function signature, including every test function — this has been the single most common review finding across every prior task in this project; get it right the first time.
- All user-facing AND admin-facing strings in English.
- Every interactive flow/menu includes a "Back" (and "Back to Menu" where relevant) button by default.
- `app/services/ibsng/client.py` is the ONLY place that calls the IBSng API — never call IBSng from handlers or other services directly.
- IBSng operations (create user) must be idempotent — `IBSngClient.create_user` already raises `IBSngUserExistsError` rather than duplicating; build on that, don't bypass it.
- New feature = new router + new service method, not a growing god-file.
- Don't add dependencies or abstractions beyond what the current feature needs.
- `app/db/models/__init__.py` must import every new model (side-effecting import pattern already established — `Base.metadata` and the test suite's table-truncation both depend on it).
- Every new migration is a frozen historical record — seed literals live inline in the migration file itself, never imported from app code (this was a real bug fixed in the bootstrap's catalog-correction work: a migration importing a mutable app-code constant let a later edit retroactively change what an already-shipped migration did).
- `app/main.py`'s `build_dispatcher(storage)` is the ONLY place that wires routers/middlewares — `tests/conftest.py`'s `dispatcher` fixture calls this exact function, so a new router added there automatically gets test coverage; never hand-wire a second copy anywhere.

---

## File Structure

```
Homeland-bot/
├── app/
│   ├── db/models/
│   │   ├── tutorial_platform.py      # NEW
│   │   ├── tutorial_protocol.py      # NEW
│   │   ├── tutorial_guide.py         # NEW
│   │   ├── openvpn_profile.py        # NEW
│   │   ├── vpn_user.py               # MODIFY: add is_trial
│   │   └── __init__.py               # MODIFY: export the 4 new models
│   ├── services/
│   │   ├── vpn_users.py              # NEW: credentials, create_vpn_user, has_used_trial
│   │   ├── tutorials.py              # NEW: platform/protocol/guide/profile CRUD + lookup
│   │   ├── tutorial_delivery.py      # NEW: deliver_setup orchestration (sends to Telegram)
│   │   └── ibsng/exceptions.py       # (unchanged, VPNUsernameTakenError lives in vpn_users.py instead - it's a local uniqueness concept, not an IBSng-API concept)
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── trial.py              # NEW: the trial flow
│   │   │   ├── tutorial_admin.py     # NEW: minimal admin content upload flow
│   │   │   └── users.py              # MODIFY: remove "menu:trial" from placeholders
│   │   ├── keyboards/
│   │   │   ├── trial.py              # NEW: trial screen keyboards
│   │   │   └── tutorial_admin.py     # NEW: admin flow keyboards
│   │   └── states/
│   │       └── tutorial_admin.py     # NEW: TutorialAdminStates
│   └── main.py                       # MODIFY: register trial.router, tutorial_admin.router
├── alembic/versions/
│   └── 0005_trial_and_tutorials.py   # NEW
└── tests/
    ├── conftest.py                    # MODIFY: extend the seed-read-back pattern to platforms/protocols
    ├── factories.py                   # MODIFY: add a photo/document message builder
    └── functional/
        ├── test_vpn_users.py                    # NEW
        ├── test_tutorials.py                    # NEW
        ├── test_tutorial_delivery.py             # NEW
        ├── test_trial_flow.py                    # NEW
        └── test_tutorial_admin_flow.py           # NEW
```

---

## Task 1: Tutorial/profile schema, seed data, and the lifetime trial-once constraint

**Files:**
- Create: `app/db/models/tutorial_platform.py`, `app/db/models/tutorial_protocol.py`, `app/db/models/tutorial_guide.py`, `app/db/models/openvpn_profile.py`
- Modify: `app/db/models/vpn_user.py`, `app/db/models/__init__.py`
- Create: `alembic/versions/0005_trial_and_tutorials.py`
- Modify: `tests/conftest.py` (extend the seed-read-back mechanism)
- Test: `tests/functional/test_vpn_user_model.py` (extend), `tests/functional/test_tutorials.py` (new, schema-level tests only in this task)

**Interfaces:**
- Produces: models `TutorialPlatform(id, label, is_active, sort_order)`, `TutorialProtocol(id, label, is_active, sort_order)`, `TutorialGuide(id, platform_id: int | None, protocol_id: int, body_html: str | None, media_file_id: str | None, media_type: str | None, is_active, sort_order)`, `OpenVpnProfile(id, name, platform_id: int | None, file_id: str | None, file_type: str | None, text: str | None, is_active, created_at)`; `VPNUser.is_trial: bool`; the partial unique index `ix_vpn_users_trial_once` on `vpn_users(telegram_id) WHERE is_trial = true`; seeded rows: 4 `TutorialPlatform` (iOS, Android, Windows, macOS) and 2 `TutorialProtocol` (L2TP, OpenVPN).

- [ ] **Step 1: Write the failing tests**

```python
# tests/functional/test_vpn_user_model.py — ADD to the existing file (don't remove existing tests)
@pytest.mark.asyncio
async def test_is_trial_defaults_false() -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=501, ibsng_username="trial_default_test", ibsng_group="Trial-Iran", data_cap_mb=1024))
        await session.commit()

    async with async_session_maker() as session:
        row = (await session.execute(select(VPNUser).where(VPNUser.ibsng_username == "trial_default_test"))).scalar_one()
    assert row.is_trial is False


@pytest.mark.asyncio
async def test_only_one_trial_vpn_user_per_telegram_id() -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=502, ibsng_username="trial_once_a", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=502, ibsng_username="trial_once_b", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_same_telegram_id_can_have_multiple_non_trial_vpn_users() -> None:
    """The partial index only restricts is_trial=true rows - a repeat
    paying customer must still be able to own more than one account."""
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=503, ibsng_username="repeat_a", ibsng_group="1M-1U-Iran-10G", data_cap_mb=10240, is_trial=False))
        session.add(VPNUser(telegram_id=503, ibsng_username="repeat_b", ibsng_group="2M-1U-Iran-20G", data_cap_mb=20480, is_trial=False))
        await session.commit()

    async with async_session_maker() as session:
        count = (
            await session.execute(select(func.count()).select_from(VPNUser).where(VPNUser.telegram_id == 503))
        ).scalar_one()
    assert count == 2
```

```python
# tests/functional/test_tutorials.py (new file)
from __future__ import annotations

import pytest

from app.db.session import async_session_maker


@pytest.mark.asyncio
async def test_seed_migration_creates_four_platforms() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_platform import TutorialPlatform

    async with async_session_maker() as session:
        rows = (await session.execute(select(TutorialPlatform).order_by(TutorialPlatform.sort_order))).scalars().all()

    assert [p.label for p in rows] == ["iOS", "Android", "Windows", "macOS"]
    assert all(p.is_active for p in rows)


@pytest.mark.asyncio
async def test_seed_migration_creates_two_protocols() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        rows = (await session.execute(select(TutorialProtocol).order_by(TutorialProtocol.sort_order))).scalars().all()

    assert [p.label for p in rows] == ["L2TP", "OpenVPN"]


@pytest.mark.asyncio
async def test_tutorial_guide_allows_one_null_platform_row_per_protocol() -> None:
    """The OpenVPN guide has platform_id=NULL (shared across platforms) -
    the partial unique index must still stop a SECOND null-platform row
    for the same protocol from being inserted."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import select

    from app.db.models.tutorial_guide import TutorialGuide
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        openvpn = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one()
        session.add(TutorialGuide(platform_id=None, protocol_id=openvpn.id, is_active=True))
        await session.commit()

    async with async_session_maker() as session:
        openvpn = (
            await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))
        ).scalar_one()
        session.add(TutorialGuide(platform_id=None, protocol_id=openvpn.id, is_active=True))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_tutorial_guide_allows_one_row_per_platform_protocol_pair() -> None:
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import select

    from app.db.models.tutorial_guide import TutorialGuide
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    async with async_session_maker() as session:
        ios = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one()
        l2tp = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one()
        session.add(TutorialGuide(platform_id=ios.id, protocol_id=l2tp.id, is_active=True))
        await session.commit()
        ios_id, l2tp_id = ios.id, l2tp.id

    async with async_session_maker() as session:
        session.add(TutorialGuide(platform_id=ios_id, protocol_id=l2tp_id, is_active=True))
        with pytest.raises(IntegrityError):
            await session.commit()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.tutorial_platform'` (and `VPNUser.is_trial` doesn't exist).

- [ ] **Step 3: Write the models**

```python
# app/db/models/tutorial_platform.py
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TutorialPlatform(Base):
    """A device/OS a user can pick (iOS, Android, Windows, macOS) - drives
    which TutorialGuide/OpenVpnProfile is shown. Seed-only for now (see
    migration 0005); admin CRUD for these is out of scope until the full
    admin panel lands."""

    __tablename__ = "tutorial_platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
```

```python
# app/db/models/tutorial_protocol.py
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TutorialProtocol(Base):
    """L2TP or OpenVPN - the two protocols Homeland offers (spec §9).
    Seed-only, same as TutorialPlatform."""

    __tablename__ = "tutorial_protocols"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
```

```python
# app/db/models/tutorial_guide.py
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TutorialGuide(Base):
    """The (platform, protocol) -> setup-instructions mapping. platform_id
    is NULL for OpenVPN (one shared guide, not per-platform - spec §2)
    and required for L2TP (4 separate guides). Two partial unique indexes
    replace one plain unique constraint because Postgres treats every
    NULL as distinct in a unique constraint - without the split, a
    second NULL-platform OpenVPN guide could be inserted with no error."""

    __tablename__ = "tutorial_guides"
    __table_args__ = (
        Index(
            "uq_tutorial_guides_no_platform", "protocol_id",
            unique=True, postgresql_where=text("platform_id IS NULL"),
        ),
        Index(
            "uq_tutorial_guides_with_platform", "platform_id", "protocol_id",
            unique=True, postgresql_where=text("platform_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int | None] = mapped_column(ForeignKey("tutorial_platforms.id"), nullable=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("tutorial_protocols.id"))
    # Optional caption alongside media_file_id - guides are expected to
    # be purely file-based (admin uploads a photo/document/video), but
    # this stays available for a text-only guide too.
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "photo" | "document" | "video"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
```

```python
# app/db/models/openvpn_profile.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OpenVpnProfile(Base):
    """An OpenVPN .ovpn config file (or inline text) an admin uploads.
    platform_id=NULL means "matches any platform" - a platform-specific
    row, if one exists, takes priority over the generic one (see
    services.tutorials.find_matching_profile). No uniqueness constraint:
    like AloBot's original, admin discipline plus "most specific match
    wins" is enough here, there's no user-facing harm from a duplicate."""

    __tablename__ = "openvpn_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    platform_id: Mapped[int | None] = mapped_column(ForeignKey("tutorial_platforms.id"), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "document" | "photo" | "video"
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Add `is_trial` to `VPNUser`**

In `app/db/models/vpn_user.py`, add the import and column:

```python
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
```

Add after `data_cap_mb`:

```python
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 5: Update `app/db/models/__init__.py`**

```python
from app.db.models.admin_user import AdminUser
from app.db.models.app_config import AppConfig
from app.db.models.bot_user import BotUser
from app.db.models.group import Group
from app.db.models.openvpn_profile import OpenVpnProfile
from app.db.models.plan import Plan
from app.db.models.tutorial_guide import TutorialGuide
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser

__all__ = [
    "AdminUser", "AppConfig", "BotUser", "Group", "OpenVpnProfile", "Plan",
    "TutorialGuide", "TutorialPlatform", "TutorialProtocol", "VPNUser",
]
```

- [ ] **Step 6: Write the migration**

```python
# alembic/versions/0005_trial_and_tutorials.py
"""trial/tutorial schema: VPNUser.is_trial + lifetime-once index,
tutorial_platforms/protocols/guides, openvpn_profiles

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15

"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_PLATFORMS: tuple[tuple[str, int], ...] = (
    ("iOS", 0), ("Android", 1), ("Windows", 2), ("macOS", 3),
)
_PROTOCOLS: tuple[tuple[str, int], ...] = (
    ("L2TP", 0), ("OpenVPN", 1),
)


def upgrade() -> None:
    op.add_column("vpn_users", sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(
        "ix_vpn_users_trial_once", "vpn_users", ["telegram_id"],
        unique=True, postgresql_where=sa.text("is_trial = true"),
    )

    op.create_table(
        "tutorial_platforms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "tutorial_protocols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "tutorial_guides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("tutorial_platforms.id"), nullable=True),
        sa.Column("protocol_id", sa.Integer(), sa.ForeignKey("tutorial_protocols.id"), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("media_file_id", sa.String(256), nullable=True),
        sa.Column("media_type", sa.String(16), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "uq_tutorial_guides_no_platform", "tutorial_guides", ["protocol_id"],
        unique=True, postgresql_where=sa.text("platform_id IS NULL"),
    )
    op.create_index(
        "uq_tutorial_guides_with_platform", "tutorial_guides", ["platform_id", "protocol_id"],
        unique=True, postgresql_where=sa.text("platform_id IS NOT NULL"),
    )
    op.create_table(
        "openvpn_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("tutorial_platforms.id"), nullable=True),
        sa.Column("file_id", sa.String(256), nullable=True),
        sa.Column("file_type", sa.String(16), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    platforms_table = sa.table("tutorial_platforms", sa.column("label", sa.String), sa.column("sort_order", sa.Integer))
    protocols_table = sa.table("tutorial_protocols", sa.column("label", sa.String), sa.column("sort_order", sa.Integer))
    op.bulk_insert(platforms_table, [{"label": label, "sort_order": order} for label, order in _PLATFORMS])
    op.bulk_insert(protocols_table, [{"label": label, "sort_order": order} for label, order in _PROTOCOLS])


def downgrade() -> None:
    op.drop_table("openvpn_profiles")
    op.drop_index("uq_tutorial_guides_with_platform", table_name="tutorial_guides")
    op.drop_index("uq_tutorial_guides_no_platform", table_name="tutorial_guides")
    op.drop_table("tutorial_guides")
    op.drop_table("tutorial_protocols")
    op.drop_table("tutorial_platforms")
    op.drop_index("ix_vpn_users_trial_once", table_name="vpn_users")
    op.drop_column("vpn_users", "is_trial")
```

- [ ] **Step 7: Extend `tests/conftest.py`'s seed-read-back mechanism to platforms/protocols**

Read the current file first — `seeded_catalog` (session-scoped) reads back `groups`/`plans` right after migration and caches them; `_clean_database` (autouse) re-inserts from that cache after every `TRUNCATE`. `tutorial_platforms`/`tutorial_protocols` need the exact same treatment (seeded once by the migration, wiped by every `TRUNCATE`) — extend the SAME fixture and re-seed step rather than adding a parallel one, since it's the same problem on the same mechanism.

Find this block near the top of the file:

```python
_SERVER_MANAGED_COLUMNS = {"id", "created_at", "updated_at", "synced_at"}
_GROUP_SEED_COLUMNS = tuple(c.name for c in Group.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)
_PLAN_SEED_COLUMNS = tuple(c.name for c in Plan.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)
```

Add the platform/protocol imports and column tuples right after it:

```python
from app.db.models.tutorial_platform import TutorialPlatform  # noqa: E402
from app.db.models.tutorial_protocol import TutorialProtocol  # noqa: E402

_PLATFORM_SEED_COLUMNS = tuple(c.name for c in TutorialPlatform.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)
_PROTOCOL_SEED_COLUMNS = tuple(c.name for c in TutorialProtocol.__table__.columns if c.name not in _SERVER_MANAGED_COLUMNS)
```

In the `seeded_catalog` fixture, add two more read-backs alongside the existing `group_rows`/`plan_rows`:

```python
        platform_rows = (
            await conn.execute(text(f"SELECT {', '.join(_PLATFORM_SEED_COLUMNS)} FROM tutorial_platforms ORDER BY id"))
        ).mappings().all()
        protocol_rows = (
            await conn.execute(text(f"SELECT {', '.join(_PROTOCOL_SEED_COLUMNS)} FROM tutorial_protocols ORDER BY id"))
        ).mappings().all()
```

Add them to the returned `cached` dict (alongside the existing `"groups"`/`"plans"` keys):

```python
        "platforms": [dict(row) for row in platform_rows],
        "protocols": [dict(row) for row in protocol_rows],
```

Extend the empty-seed guard's condition to also check these two lists are non-empty (`or not cached["platforms"] or not cached["protocols"]`).

In `_clean_database`, add two more re-insert loops alongside the existing `group_stmt`/`plan_stmt` ones:

```python
        platform_stmt = text(_insert_statement("tutorial_platforms", _PLATFORM_SEED_COLUMNS))
        for row in seeded_catalog["platforms"]:
            await conn.execute(platform_stmt, row)

        protocol_stmt = text(_insert_statement("tutorial_protocols", _PROTOCOL_SEED_COLUMNS))
        for row in seeded_catalog["protocols"]:
            await conn.execute(protocol_stmt, row)
```

Order matters: `tutorial_guides`/`openvpn_profiles` will (in later tasks' tests) FK-reference `tutorial_platforms`/`tutorial_protocols`, so those two re-inserts must run before anything that references them — but nothing in THIS task's own tests creates guides/profiles as part of the reseed step itself (that's per-test data, not seeded reference data), so ordering relative to `group_stmt`/`plan_stmt` doesn't matter here. Keep the type hint on `seeded_catalog`'s return updated: `dict[str, list[dict[str, Any]]]` already covers this (no signature change needed, just more keys in the dict).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `make test`
Expected: PASS — the new tests in `test_vpn_user_model.py` and `test_tutorials.py`, plus everything from the bootstrap and catalog-correction work.

- [ ] **Step 9: Run twice more to confirm the migration's downgrade/upgrade cycle is stable**

Run: `make test` (again, without `test-down` in between) then `make test-down && make test`.
Expected: PASS both times — this project's history includes a real bug (Task 6's original `downgrade()`) that only surfaced on a second run against an already-migrated database; don't skip this check.

- [ ] **Step 10: Commit**

```bash
git add app/db/models/tutorial_platform.py app/db/models/tutorial_protocol.py app/db/models/tutorial_guide.py \
        app/db/models/openvpn_profile.py app/db/models/vpn_user.py app/db/models/__init__.py \
        alembic/versions/0005_trial_and_tutorials.py tests/conftest.py \
        tests/functional/test_vpn_user_model.py tests/functional/test_tutorials.py
git commit -m "feat: tutorial/profile schema, VPNUser.is_trial, lifetime trial-once index"
```

---

## Task 2: Credential generation and the shared `create_vpn_user` service

**Files:**
- Create: `app/services/vpn_users.py`
- Test: `tests/functional/test_vpn_users.py`

**Interfaces:**
- Consumes: `IBSngClient.create_user(*, username, password, group_name, credit) -> str` and `IBSngUserExistsError`/`IBSngError` (Task 5 of the bootstrap plan), `VPNUser` model with `is_trial` (Task 1 of this plan).
- Produces: `generate_vpn_credentials() -> tuple[str, str]`, `VPNUsernameTakenError(Exception)`, `create_vpn_user(session, client, *, telegram_id: int, username: str, password: str, group_name: str, data_cap_mb: int, plan_id: int | None = None, is_trial: bool = False) -> VPNUser`, `has_used_trial(session, telegram_id: int) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/functional/test_vpn_users.py
from __future__ import annotations

import pytest

from app.db.session import async_session_maker
from app.services.ibsng.client import IBSngClient
from tests.fakes.fake_ibsng_server import FakeIBSngServer


def test_generate_vpn_credentials_shape() -> None:
    from app.services.vpn_users import generate_vpn_credentials

    username, password = generate_vpn_credentials()
    assert username.startswith("hl.")
    assert len(username) == len("hl.") + 6
    assert len(password) == 6
    assert any(c.isalpha() for c in password)
    assert any(c.isdigit() for c in password)


def test_generate_vpn_credentials_are_random() -> None:
    from app.services.vpn_users import generate_vpn_credentials

    pairs = {generate_vpn_credentials() for _ in range(20)}
    assert len(pairs) == 20


@pytest.mark.asyncio
async def test_create_vpn_user_creates_ibsng_and_local_row(ibsng_server: FakeIBSngServer) -> None:
    from app.services.vpn_users import create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        vpn_user = await create_vpn_user(
            session, client,
            telegram_id=601, username="hl.abc123", password="ab12cd",
            group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
        )

    assert vpn_user.ibsng_username == "hl.abc123"
    assert vpn_user.ibsng_group == "Trial-Iran"
    assert vpn_user.is_trial is True
    assert vpn_user.data_cap_mb == 1024

    async with IBSngClient() as client:
        info = await client.get_user_info(username="hl.abc123")
    assert info is not None


@pytest.mark.asyncio
async def test_create_vpn_user_rejects_duplicate_local_username(ibsng_server: FakeIBSngServer) -> None:
    from app.services.vpn_users import VPNUsernameTakenError, create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=602, username="hl.dup001", password="ab12cd",
            group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
        )

    async with async_session_maker() as session, IBSngClient() as client:
        with pytest.raises(VPNUsernameTakenError):
            await create_vpn_user(
                session, client, telegram_id=603, username="hl.dup001", password="ef34gh",
                group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
            )


@pytest.mark.asyncio
async def test_create_vpn_user_rejects_second_trial_for_same_telegram_id(ibsng_server: FakeIBSngServer) -> None:
    """Exercises the DB partial-unique-index backstop from Task 1, via
    create_vpn_user's IntegrityError catch - a second trial attempt for
    the same telegram_id must surface as the same VPNUsernameTakenError,
    not an unhandled IntegrityError."""
    from app.services.vpn_users import VPNUsernameTakenError, create_vpn_user

    async with async_session_maker() as session, IBSngClient() as client:
        await create_vpn_user(
            session, client, telegram_id=604, username="hl.trial01", password="ab12cd",
            group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
        )

    async with async_session_maker() as session, IBSngClient() as client:
        with pytest.raises(VPNUsernameTakenError):
            await create_vpn_user(
                session, client, telegram_id=604, username="hl.trial02", password="ef34gh",
                group_name="Trial-Iran", data_cap_mb=1024, is_trial=True,
            )


@pytest.mark.asyncio
async def test_has_used_trial() -> None:
    from app.services.vpn_users import has_used_trial

    async with async_session_maker() as session:
        assert await has_used_trial(session, 605) is False

    async with async_session_maker() as session:
        from app.db.models.vpn_user import VPNUser

        session.add(VPNUser(telegram_id=605, ibsng_username="hl.hastrial", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    async with async_session_maker() as session:
        assert await has_used_trial(session, 605) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.vpn_users'`.

- [ ] **Step 3: Write the service**

```python
# app/services/vpn_users.py
from __future__ import annotations

import secrets
import string

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vpn_user import VPNUser
from app.services.ibsng.client import IBSngClient

_CREDENTIAL_CHARS = string.ascii_lowercase + string.digits
_USERNAME_PREFIX = "hl."
_USERNAME_SUFFIX_LEN = 6
_PASSWORD_LEN = 6


class VPNUsernameTakenError(Exception):
    """Raised when a generated username collides locally, in IBSng, or
    (for a trial) when the DB's partial unique index rejects a second
    is_trial=true row for the same telegram_id - all three are the same
    "this account can't be created as requested" situation from the
    caller's point of view."""


def _random_password(length: int) -> str:
    while True:
        candidate = "".join(secrets.choice(_CREDENTIAL_CHARS) for _ in range(length))
        if any(c.isalpha() for c in candidate) and any(c.isdigit() for c in candidate):
            return candidate


def generate_vpn_credentials() -> tuple[str, str]:
    """Bot-generated, never typed by the user - same scheme for trial
    and (later) paid purchases. Ported from AloBot's generate_vpn_credentials
    with Homeland's own username prefix."""
    suffix = "".join(secrets.choice(_CREDENTIAL_CHARS) for _ in range(_USERNAME_SUFFIX_LEN))
    return f"{_USERNAME_PREFIX}{suffix}", _random_password(_PASSWORD_LEN)


async def create_vpn_user(
    session: AsyncSession,
    client: IBSngClient,
    *,
    telegram_id: int,
    username: str,
    password: str,
    group_name: str,
    data_cap_mb: int,
    plan_id: int | None = None,
    is_trial: bool = False,
) -> VPNUser:
    """The one account-creation path - trial and (later) paid purchases
    both call this, differentiated only by is_trial/plan_id. Sequence:
    local uniqueness pre-check (avoids creating an orphan IBSng account
    for a username we already know is taken) -> IBSng account creation
    -> local row insert -> IntegrityError as a race-condition backstop
    (covers a username collision AND, via the partial unique index on
    is_trial, a duplicate trial claim - both surface as the same
    VPNUsernameTakenError)."""
    existing = await session.execute(select(VPNUser).where(VPNUser.ibsng_username == username))
    if existing.scalar_one_or_none() is not None:
        raise VPNUsernameTakenError(f"{username!r} already exists locally")

    await client.create_user(username=username, password=password, group_name=group_name, credit=data_cap_mb)

    vpn_user = VPNUser(
        telegram_id=telegram_id,
        ibsng_username=username,
        ibsng_group=group_name,
        plan_id=plan_id,
        data_cap_mb=data_cap_mb,
        is_trial=is_trial,
    )
    session.add(vpn_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise VPNUsernameTakenError(f"{username!r} lost a creation race") from exc
    await session.refresh(vpn_user)
    return vpn_user


async def has_used_trial(session: AsyncSession, telegram_id: int) -> bool:
    result = await session.execute(
        select(VPNUser.id).where(VPNUser.telegram_id == telegram_id, VPNUser.is_trial.is_(True)).limit(1)
    )
    return result.scalar_one_or_none() is not None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test`
Expected: PASS — all new tests in `test_vpn_users.py`, plus everything from Task 1 and the bootstrap/catalog work.

- [ ] **Step 5: Commit**

```bash
git add app/services/vpn_users.py tests/functional/test_vpn_users.py
git commit -m "feat: credential generation and shared create_vpn_user service"
```

---

## Task 3: Tutorial/profile lookup and delivery service

**Files:**
- Create: `app/services/tutorials.py`, `app/services/tutorial_delivery.py`
- Test: `tests/functional/test_tutorials.py` (extend from Task 1), `tests/functional/test_tutorial_delivery.py`

**Interfaces:**
- Consumes: `TutorialPlatform`, `TutorialProtocol`, `TutorialGuide`, `OpenVpnProfile` (Task 1); `app.services.app_config.get_config(session, key) -> str | None` (bootstrap slice); `FakeBotSession`/`fake_session.calls` (existing test harness).
- Produces: `tutorials.list_platforms(session, *, active_only=True) -> list[TutorialPlatform]`, `tutorials.list_protocols(session, *, active_only=True) -> list[TutorialProtocol]`, `tutorials.get_guide(session, *, platform_id: int | None, protocol_id: int) -> TutorialGuide | None`, `tutorials.find_matching_profile(session, *, platform_id: int | None) -> OpenVpnProfile | None`, `tutorials.is_protocol_valid_for_platform(platform_label: str, protocol_label: str) -> bool`, `tutorials.upsert_guide(session, *, platform_id, protocol_id, media_file_id, media_type) -> TutorialGuide`, `tutorials.upsert_profile(session, *, platform_id, name, file_id, file_type, text) -> OpenVpnProfile`; `tutorial_delivery.deliver_setup(bot, telegram_id: int, session, *, protocol_id: int, platform_id: int | None) -> tuple[bool, int | None]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/functional/test_tutorials.py — ADD to the file created in Task 1
@pytest.mark.asyncio
async def test_is_protocol_valid_for_platform_blocks_android_l2tp() -> None:
    from app.services.tutorials import is_protocol_valid_for_platform

    assert is_protocol_valid_for_platform("Android", "L2TP") is False
    assert is_protocol_valid_for_platform("iOS", "L2TP") is True
    assert is_protocol_valid_for_platform("Android", "OpenVPN") is True


@pytest.mark.asyncio
async def test_upsert_guide_creates_then_updates() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_guide import TutorialGuide
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorials import get_guide, upsert_guide

    async with async_session_maker() as session:
        ios = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one()
        l2tp = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one()
        ios_id, l2tp_id = ios.id, l2tp.id
        created = await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id="file-1", media_type="photo")

    assert created.media_file_id == "file-1"

    async with async_session_maker() as session:
        updated = await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id="file-2", media_type="document")

    assert updated.id == created.id
    assert updated.media_file_id == "file-2"
    assert updated.media_type == "document"

    async with async_session_maker() as session:
        count = (await session.execute(select(TutorialGuide))).scalars().all()
    assert len(count) == 1


@pytest.mark.asyncio
async def test_get_guide_returns_none_when_not_configured() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorials import get_guide

    async with async_session_maker() as session:
        openvpn = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one()
        guide = await get_guide(session, platform_id=None, protocol_id=openvpn.id)

    assert guide is None


@pytest.mark.asyncio
async def test_find_matching_profile_prefers_platform_specific_over_generic() -> None:
    from sqlalchemy import select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.services.tutorials import find_matching_profile, upsert_profile

    async with async_session_maker() as session:
        ios = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one()
        ios_id = ios.id
        await upsert_profile(session, platform_id=None, name="Generic", file_id="generic-file", file_type="document", text=None)
        await upsert_profile(session, platform_id=ios_id, name="iOS-specific", file_id="ios-file", file_type="document", text=None)

    async with async_session_maker() as session:
        matched = await find_matching_profile(session, platform_id=ios_id)
    assert matched is not None
    assert matched.name == "iOS-specific"

    async with async_session_maker() as session:
        android_id = (
            await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "Android"))
        ).scalar_one().id
        fallback = await find_matching_profile(session, platform_id=android_id)
    assert fallback is not None
    assert fallback.name == "Generic"
```

```python
# tests/functional/test_tutorial_delivery.py
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_deliver_setup_blocks_android_l2tp(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup

    async with async_session_maker() as session:
        android_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "Android"))).scalar_one().id
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        delivered, guide_message_id = await deliver_setup(bot, 701, session, protocol_id=l2tp_id, platform_id=android_id)

    assert delivered is False
    assert guide_message_id is None
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("android" in c[1]["text"].lower() or "l2tp" in c[1]["text"].lower() for c in sent)


@pytest.mark.asyncio
async def test_deliver_setup_sends_guide_and_credentials_placeholder_when_configured(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup
    from app.services.tutorials import upsert_guide

    async with async_session_maker() as session:
        ios_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        await upsert_guide(session, platform_id=ios_id, protocol_id=l2tp_id, media_file_id=None, media_type=None)

    async with async_session_maker() as session:
        delivered, guide_message_id = await deliver_setup(bot, 702, session, protocol_id=l2tp_id, platform_id=ios_id)

    assert delivered is True
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert len(sent) >= 1


@pytest.mark.asyncio
async def test_deliver_setup_falls_back_gracefully_when_no_guide_configured(bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.tutorial_delivery import deliver_setup

    async with async_session_maker() as session:
        macos_id = (await session.execute(select(TutorialPlatform).where(TutorialPlatform.label == "macOS"))).scalar_one().id
        l2tp_id = (await session.execute(select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        delivered, _ = await deliver_setup(bot, 703, session, protocol_id=l2tp_id, platform_id=macos_id)

    assert delivered is True
    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("not ready" in c[1]["text"].lower() for c in sent)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.tutorials'`.

- [ ] **Step 3: Write `app/services/tutorials.py`**

```python
# app/services/tutorials.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.openvpn_profile import OpenVpnProfile
from app.db.models.tutorial_guide import TutorialGuide
from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol


async def list_platforms(session: AsyncSession, *, active_only: bool = True) -> list[TutorialPlatform]:
    query = select(TutorialPlatform).order_by(TutorialPlatform.sort_order, TutorialPlatform.id)
    if active_only:
        query = query.where(TutorialPlatform.is_active.is_(True))
    return list((await session.execute(query)).scalars().all())


async def list_protocols(session: AsyncSession, *, active_only: bool = True) -> list[TutorialProtocol]:
    query = select(TutorialProtocol).order_by(TutorialProtocol.sort_order, TutorialProtocol.id)
    if active_only:
        query = query.where(TutorialProtocol.is_active.is_(True))
    return list((await session.execute(query)).scalars().all())


async def get_guide(session: AsyncSession, *, platform_id: int | None, protocol_id: int) -> TutorialGuide | None:
    query = select(TutorialGuide).where(
        TutorialGuide.protocol_id == protocol_id,
        TutorialGuide.is_active.is_(True),
    )
    query = query.where(TutorialGuide.platform_id.is_(None) if platform_id is None else TutorialGuide.platform_id == platform_id)
    return (await session.execute(query)).scalar_one_or_none()


async def upsert_guide(
    session: AsyncSession, *, platform_id: int | None, protocol_id: int,
    media_file_id: str | None, media_type: str | None,
) -> TutorialGuide:
    guide = await get_guide(session, platform_id=platform_id, protocol_id=protocol_id)
    if guide is None:
        guide = TutorialGuide(platform_id=platform_id, protocol_id=protocol_id)
        session.add(guide)
    guide.media_file_id = media_file_id
    guide.media_type = media_type
    await session.commit()
    await session.refresh(guide)
    return guide


async def find_matching_profile(session: AsyncSession, *, platform_id: int | None) -> OpenVpnProfile | None:
    """A platform-specific active profile wins over the generic
    (platform_id=NULL) one, if both exist. Ported from AloBot's
    find_matching_profile, minus the category/location dimension
    Homeland doesn't have."""
    result = await session.execute(select(OpenVpnProfile).where(OpenVpnProfile.is_active.is_(True)))
    candidates = list(result.scalars().all())
    if not candidates:
        return None
    specific = next((p for p in candidates if p.platform_id == platform_id and platform_id is not None), None)
    if specific is not None:
        return specific
    return next((p for p in candidates if p.platform_id is None), None)


async def upsert_profile(
    session: AsyncSession, *, platform_id: int | None, name: str,
    file_id: str | None, file_type: str | None, text: str | None,
) -> OpenVpnProfile:
    profile = OpenVpnProfile(platform_id=platform_id, name=name, file_id=file_id, file_type=file_type, text=text)
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


def is_protocol_valid_for_platform(platform_label: str, protocol_label: str) -> bool:
    """Android 12+ dropped its built-in L2TP/IPsec client - a real OS
    constraint, not a Homeland business rule. Ported from AloBot's
    is_protocol_valid_for_platform."""
    is_android = platform_label.strip().lower() == "android"
    is_l2tp = protocol_label.strip().lower() == "l2tp"
    return not (is_android and is_l2tp)
```

- [ ] **Step 4: Write `app/services/tutorial_delivery.py`**

```python
# app/services/tutorial_delivery.py
from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol
from app.services.app_config import get_config
from app.services.tutorials import find_matching_profile, get_guide, is_protocol_valid_for_platform, list_platforms

_MEDIA_SENDERS = {"photo": "send_photo", "document": "send_document", "video": "send_video"}

_ANDROID_L2TP_MESSAGE = (
    "⚠️ L2TP isn't supported on Android 12 and newer (Google removed the "
    "built-in L2TP/IPsec client). Please use OpenVPN instead, or contact "
    "support for help."
)
_GUIDE_NOT_READY_MESSAGE = "📚 This guide isn't ready yet — please contact support."


async def _send_media_or_text(bot: Bot, telegram_id: int, *, file_id: str | None, file_type: str | None, text: str | None, fallback_prefix: str) -> None:
    if file_id is not None and file_type is not None:
        sender = getattr(bot, _MEDIA_SENDERS.get(file_type, "send_document"))
        await sender(telegram_id, file_id, caption=text or None)
        return
    if text is not None:
        await bot.send_message(telegram_id, f"{fallback_prefix}\n\n{text}")


async def deliver_setup(
    bot: Bot, telegram_id: int, session: AsyncSession, *, protocol_id: int, platform_id: int | None,
) -> tuple[bool, int | None]:
    """Shared by the trial flow now, Buy/Renew later. Sends the OpenVPN
    profile, the tutorial guide, and any configured download link - it
    does NOT send account credentials, since not every future caller
    will want the same closing message (and the caller, not this
    function, is the one that actually has the username/password in
    scope). Returns (delivered, guide_message_id) - delivered=False
    means the caller must NOT send its own credentials message either
    (currently only the Android+L2TP compatibility gate triggers this)."""
    protocol = await session.get(TutorialProtocol, protocol_id)
    platform = await session.get(TutorialPlatform, platform_id) if platform_id is not None else None

    if platform is not None and not is_protocol_valid_for_platform(platform.label, protocol.label):
        await bot.send_message(telegram_id, _ANDROID_L2TP_MESSAGE)
        return False, None

    if protocol.label.strip().lower() == "openvpn":
        profile = await find_matching_profile(session, platform_id=platform_id)
        if profile is not None:
            await _send_media_or_text(
                bot, telegram_id, file_id=profile.file_id, file_type=profile.file_type,
                text=profile.text, fallback_prefix=f"📡 Connection profile ({profile.name})",
            )

    guide = await get_guide(session, platform_id=platform_id, protocol_id=protocol_id)
    guide_message_id: int | None = None
    if guide is not None and (guide.media_file_id is not None or guide.body_html is not None):
        if guide.media_file_id is not None and guide.media_type is not None:
            sender = getattr(bot, _MEDIA_SENDERS.get(guide.media_type, "send_document"))
            message = await sender(telegram_id, guide.media_file_id, caption=guide.body_html or None)
        else:
            message = await bot.send_message(telegram_id, guide.body_html or "")
        guide_message_id = message.message_id
    else:
        await bot.send_message(telegram_id, _GUIDE_NOT_READY_MESSAGE)

    protocol_key = protocol.label.strip().lower()
    if platform is not None:
        link = await get_config(session, f"download_link:{protocol_key}:{platform.label.strip().lower()}")
        if link:
            await bot.send_message(telegram_id, f"📥 App download link:\n{link}")
    else:
        # No platform was picked (OpenVPN's shared-guide path) - show every
        # configured platform's link at once so the user can pick their own.
        links = []
        for candidate_platform in await list_platforms(session):
            candidate_link = await get_config(session, f"download_link:{protocol_key}:{candidate_platform.label.strip().lower()}")
            if candidate_link:
                links.append(f"{candidate_platform.label}: {candidate_link}")
        if links:
            await bot.send_message(telegram_id, "📥 Download OpenVPN Connect:\n" + "\n".join(links))

    return True, guide_message_id
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test`
Expected: PASS — all tests in `test_tutorials.py` and `test_tutorial_delivery.py`, plus everything from Tasks 1-2 and the bootstrap/catalog work.

- [ ] **Step 6: Commit**

```bash
git add app/services/tutorials.py app/services/tutorial_delivery.py \
        tests/functional/test_tutorials.py tests/functional/test_tutorial_delivery.py
git commit -m "feat: tutorial/profile lookup and delivery services"
```

---

## Task 4: The trial flow

**Files:**
- Create: `app/bot/keyboards/trial.py`, `app/bot/handlers/trial.py`
- Modify: `app/bot/handlers/users.py`, `app/main.py`
- Test: `tests/functional/test_trial_flow.py`

**Interfaces:**
- Consumes: `has_used_trial`, `generate_vpn_credentials`, `create_vpn_user`, `VPNUsernameTakenError` (Task 2); `deliver_setup` (Task 3); `list_platforms`, `list_protocols` (Task 3); `catalog.list_plans(session, *, category=None, active_only=True) -> list[Plan]` (bootstrap slice); `IBSngError`, `IBSngUserExistsError` (bootstrap slice).
- Produces: `trial.router` (aiogram `Router`, registered in `build_dispatcher`); callback data namespace `trial:*`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/functional/test_trial_flow.py
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import make_callback_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_trial_entry_shows_confirm_for_eligible_user(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_callback_update(801, "menu:trial")
    await dispatcher.feed_update(bot, update)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "24" in edited[0][1]["text"] and "1gb" in edited[0][1]["text"].lower()
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("confirm" in b.lower() or "start" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_trial_entry_shows_already_used_message(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from app.db.models.vpn_user import VPNUser

    async with async_session_maker() as session:
        session.add(VPNUser(telegram_id=802, ibsng_username="hl.already1", ibsng_group="Trial-Iran", data_cap_mb=1024, is_trial=True))
        await session.commit()

    update = make_callback_update(802, "menu:trial")
    await dispatcher.feed_update(bot, update)

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "already used" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_trial_confirm_creates_account_then_shows_protocol_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_callback_update(803, "trial:confirm")
    await dispatcher.feed_update(bot, update)

    async with async_session_maker() as session:
        from app.db.models.vpn_user import VPNUser

        vpn_user = (await session.execute(select(VPNUser).where(VPNUser.telegram_id == 803))).scalar_one()
    assert vpn_user.is_trial is True
    assert vpn_user.ibsng_group == "Trial-Iran"
    assert vpn_user.data_cap_mb == 1024

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("l2tp" in b.lower() for b in buttons)
    assert any("openvpn" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_trial_confirm_twice_shows_already_used_second_time(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    await dispatcher.feed_update(bot, make_callback_update(804, "trial:confirm"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(804, "menu:trial"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    assert "already used" in edited[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_trial_openvpn_protocol_skips_platform_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_callback_update(805, "trial:confirm"))
    fake_session.reset()

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(805, f"trial:protocol:{openvpn_id}"))

    sent = [c for c in fake_session.calls if c[0] in ("sendMessage", "editMessageText")]
    assert any("ready" in c[1]["text"].lower() or "hl." in c[1]["text"] for c in sent)


@pytest.mark.asyncio
async def test_trial_l2tp_protocol_shows_platform_picker(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_callback_update(806, "trial:confirm"))
    fake_session.reset()

    async with async_session_maker() as session:
        l2tp_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(806, f"trial:protocol:{l2tp_id}"))

    edited = [c for c in fake_session.calls if c[0] == "editMessageText"]
    assert len(edited) == 1
    buttons = [b["text"] for row in edited[0][1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("ios" in b.lower() for b in buttons)
    assert any("android" in b.lower() for b in buttons)


@pytest.mark.asyncio
async def test_trial_platform_pick_delivers_and_sends_credentials(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_callback_update(807, "trial:confirm"))

    async with async_session_maker() as session:
        l2tp_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        ios_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(807, f"trial:protocol:{l2tp_id}"))
    fake_session.reset()
    await dispatcher.feed_update(bot, make_callback_update(807, f"trial:platform:{ios_id}"))

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert any("hl." in c[1]["text"] and "24" in c[1]["text"] for c in sent)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bot.handlers.trial'`.

- [ ] **Step 3: Write the keyboards**

```python
# app/bot/keyboards/trial.py
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol


def trial_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm", callback_data="trial:confirm", style="success")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(1)
    return builder.as_markup()


def trial_protocol_keyboard(protocols: list[TutorialProtocol]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"trial:protocol:{protocol.id}")
    builder.button(text="⬅️ Back to Menu", callback_data="menu:root")
    builder.adjust(2, 1)
    return builder.as_markup()


def trial_platform_keyboard(platforms: list[TutorialPlatform]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"trial:platform:{platform.id}")
    builder.button(text="⬅️ Back", callback_data="trial:back_to_protocol")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
```

- [ ] **Step 4: Write the handler**

```python
# app/bot/handlers/trial.py
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.keyboards.trial import back_to_menu_keyboard, trial_confirm_keyboard, trial_platform_keyboard, trial_protocol_keyboard
from app.db.models.tutorial_protocol import TutorialProtocol
from app.db.models.vpn_user import VPNUser
from app.db.session import async_session_maker
from app.services.catalog import list_plans
from app.services.ibsng.client import IBSngClient
from app.services.ibsng.exceptions import IBSngError, IBSngUserExistsError
from app.services.tutorial_delivery import deliver_setup
from app.services.tutorials import list_platforms, list_protocols
from app.services.vpn_users import VPNUsernameTakenError, create_vpn_user, generate_vpn_credentials, has_used_trial

router = Router(name="trial")

_ALREADY_USED_TEXT = "🎁 You've already used your free trial."
_CONFIRM_TEXT = "🎁 <b>Free Trial</b> — 24 hours, 1GB of data.\n\nStart your trial?"
_CREATE_FAILED_TEXT = "⚠️ Couldn't create your trial right now. Please try again shortly."
_MAX_CREATE_ATTEMPTS = 3


async def _send_trial_credentials(bot: Bot, telegram_id: int) -> None:
    """deliver_setup (Task 3) deliberately does NOT send the account's
    username/password - it's a generic (platform, protocol) -> content
    function reused later by Buy/Renew, which won't always want the
    same trial-specific closing message. The credentials themselves were
    generated back in trial_confirm_cb, a separate callback invocation
    with nothing carried forward (no FSM state, by design - see the
    spec's rationale for not putting a password in callback_data), so
    they're looked up fresh here: the just-created VPNUser row gives the
    username, and IBSngClient.get_user_password re-reads the password
    IBSng already has stored for it (same accessor AloBot's own renew
    flow uses to re-show an existing password)."""
    async with async_session_maker() as session:
        vpn_user = (
            await session.execute(
                select(VPNUser)
                .where(VPNUser.telegram_id == telegram_id, VPNUser.is_trial.is_(True))
                .order_by(VPNUser.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if vpn_user is None:
        return

    async with IBSngClient() as client:
        password = await client.get_user_password(username=vpn_user.ibsng_username)

    await bot.send_message(
        telegram_id,
        "🎁 <b>Your trial is ready.</b>\n\n"
        f"Username: <code>{vpn_user.ibsng_username}</code>\n"
        f"Password: <code>{password}</code>\n\n"
        "⏱ Valid for 24 hours from first connection.",
    )


@router.callback_query(F.data == "menu:trial")
async def trial_entry_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        already_used = await has_used_trial(session, callback.from_user.id)

    if callback.message is None:
        await callback.answer()
        return
    if already_used:
        await callback.message.edit_text(_ALREADY_USED_TEXT, reply_markup=back_to_menu_keyboard())
    else:
        await callback.message.edit_text(_CONFIRM_TEXT, reply_markup=trial_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data == "trial:confirm")
async def trial_confirm_cb(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        trial_plans = await list_plans(session, category="trial")
    trial_plan = trial_plans[0]

    vpn_user = None
    last_error: str | None = None
    for _attempt in range(_MAX_CREATE_ATTEMPTS):
        username, password = generate_vpn_credentials()
        async with async_session_maker() as session, IBSngClient() as client:
            try:
                vpn_user = await create_vpn_user(
                    session, client,
                    telegram_id=telegram_id, username=username, password=password,
                    group_name=trial_plan.group_name, data_cap_mb=trial_plan.data_cap_mb,
                    plan_id=trial_plan.id, is_trial=True,
                )
                break
            except (VPNUsernameTakenError, IBSngUserExistsError):
                last_error = "taken"
                continue
            except IBSngError:
                last_error = "ibsng"
                break

    if vpn_user is None:
        if callback.message is not None:
            text = _ALREADY_USED_TEXT if last_error == "taken" else _CREATE_FAILED_TEXT
            await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard())
        await callback.answer()
        return

    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text(
            "🔌 Which protocol do you want to use?", reply_markup=trial_protocol_keyboard(protocols)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("trial:protocol:"))
async def trial_protocol_cb(callback: CallbackQuery) -> None:
    protocol_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocol = await session.get(TutorialProtocol, protocol_id)

    if protocol is not None and protocol.label.strip().lower() == "openvpn":
        async with async_session_maker() as session:
            delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=protocol_id, platform_id=None)
        if delivered:
            await _send_trial_credentials(callback.bot, callback.from_user.id)
        await callback.answer()
        return

    async with async_session_maker() as session:
        platforms = await list_platforms(session)
    if callback.message is not None:
        await callback.message.edit_text(
            "📱 Which device do you want to set it up on?",
            reply_markup=trial_platform_keyboard(platforms),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("trial:platform:"))
async def trial_platform_cb(callback: CallbackQuery) -> None:
    platform_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    l2tp = next(p for p in protocols if p.label.strip().lower() == "l2tp")

    async with async_session_maker() as session:
        delivered, _ = await deliver_setup(callback.bot, callback.from_user.id, session, protocol_id=l2tp.id, platform_id=platform_id)
    if delivered:
        await _send_trial_credentials(callback.bot, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "trial:back_to_protocol")
async def trial_back_to_protocol_cb(callback: CallbackQuery) -> None:
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text("🔌 Which protocol do you want to use?", reply_markup=trial_protocol_keyboard(protocols))
    await callback.answer()
```

- [ ] **Step 5: Wire the router and remove the placeholder**

In `app/bot/handlers/users.py`, remove `"menu:trial"` from `_PLACEHOLDER_CALLBACKS`:

```python
_PLACEHOLDER_CALLBACKS = {
    "menu:buy",
    "menu:renew",
    "menu:myservices",
    "menu:tutorials",
    "adm:root",
}
```

In `app/main.py`'s `build_dispatcher`, add the import and registration:

```python
from app.bot.handlers import fallback, trial, users
```

```python
    dp.include_router(users.router)
    dp.include_router(trial.router)
    dp.include_router(fallback.router)
```

(`trial.router` before `fallback.router` — `fallback` is a catch-all registered last, same ordering rule as every other router.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `make test`
Expected: PASS — all tests in `test_trial_flow.py`. Also re-run `tests/functional/test_start_and_menu.py::test_placeholder_callbacks_answer_coming_soon` specifically — it iterates a fixed callback list that must no longer include `"menu:trial"`; update that test's list (remove `"menu:trial"`) if it's still there.

- [ ] **Step 7: Commit**

```bash
git add app/bot/keyboards/trial.py app/bot/handlers/trial.py app/bot/handlers/users.py app/main.py \
        tests/functional/test_trial_flow.py tests/functional/test_start_and_menu.py
git commit -m "feat: free trial flow"
```

---

## Task 5: Minimal admin content upload flow

**Files:**
- Create: `app/bot/states/tutorial_admin.py`, `app/bot/keyboards/tutorial_admin.py`, `app/bot/handlers/tutorial_admin.py`
- Modify: `app/main.py`, `tests/factories.py`
- Test: `tests/functional/test_tutorial_admin_flow.py`

**Interfaces:**
- Consumes: `has_level(session, telegram_id, "support") -> bool` (bootstrap slice); `list_platforms`, `list_protocols`, `upsert_guide`, `upsert_profile` (Task 3); `app.services.app_config.set_config(session, key, value) -> None` (bootstrap slice).
- Produces: `tutorial_admin.router` (registered in `build_dispatcher`); command `/admintutorials`; FSM states `TutorialAdminStates`.

- [ ] **Step 1: Add a photo-message factory helper**

In `tests/factories.py`, add a photo-carrying message builder (the existing `make_message`/`make_message_update` only build text messages):

```python
def make_photo_message(telegram_id: int, *, file_id: str, username: str | None = None) -> Message:
    from aiogram.types import PhotoSize

    return Message(
        message_id=next(_message_id_counter),
        date=dt.datetime.now(dt.timezone.utc),
        chat=Chat(id=telegram_id, type="private"),
        from_user=make_user(telegram_id, username=username),
        photo=[PhotoSize(file_id=file_id, file_unique_id=f"{file_id}-unique", width=100, height=100)],
    )


def make_photo_message_update(telegram_id: int, *, file_id: str, username: str | None = None) -> Update:
    return Update(update_id=next(_update_id_counter), message=make_photo_message(telegram_id, file_id=file_id, username=username))
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/functional/test_tutorial_admin_flow.py
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import async_session_maker
from tests.factories import FAKE_ADMIN_ID, make_callback_update, make_message_update, make_photo_message_update
from tests.fakes.fake_bot_session import FakeBotSession


@pytest.mark.asyncio
async def test_non_admin_cannot_open_tutorial_admin(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    update = make_message_update(901, "/admintutorials")
    await dispatcher.feed_update(bot, update)

    sent = [c for c in fake_session.calls if c[0] == "sendMessage"]
    assert not any("tutorial" in c[1].get("text", "").lower() and "platform" in c[1].get("text", "").lower() for c in sent)


@pytest.mark.asyncio
async def test_admin_uploads_a_guide_end_to_end(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))

    async with async_session_maker() as session:
        l2tp_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "L2TP"))).scalar_one().id
        ios_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:guide"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:protocol:{l2tp_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:guide:platform:{ios_id}"))
    await dispatcher.feed_update(bot, make_photo_message_update(FAKE_ADMIN_ID, file_id="admin-uploaded-file"))

    async with async_session_maker() as session:
        from app.db.models.tutorial_guide import TutorialGuide

        guide = (
            await session.execute(
                select(TutorialGuide).where(TutorialGuide.platform_id == ios_id, TutorialGuide.protocol_id == l2tp_id)
            )
        ).scalar_one()
    assert guide.media_file_id == "admin-uploaded-file"
    assert guide.media_type == "photo"


@pytest.mark.asyncio
async def test_admin_sets_a_download_link(dispatcher: Any, bot: Any, fake_session: FakeBotSession) -> None:
    from sqlalchemy import select as sa_select

    from app.db.models.tutorial_platform import TutorialPlatform
    from app.db.models.tutorial_protocol import TutorialProtocol
    from app.services.app_config import get_config

    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "/admintutorials"))

    async with async_session_maker() as session:
        openvpn_id = (await session.execute(sa_select(TutorialProtocol).where(TutorialProtocol.label == "OpenVPN"))).scalar_one().id
        ios_id = (await session.execute(sa_select(TutorialPlatform).where(TutorialPlatform.label == "iOS"))).scalar_one().id

    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, "tutadm:link"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:link:protocol:{openvpn_id}"))
    await dispatcher.feed_update(bot, make_callback_update(FAKE_ADMIN_ID, f"tutadm:link:platform:{ios_id}"))
    await dispatcher.feed_update(bot, make_message_update(FAKE_ADMIN_ID, "https://apps.apple.com/openvpn-connect"))

    async with async_session_maker() as session:
        link = await get_config(session, "download_link:openvpn:ios")
    assert link == "https://apps.apple.com/openvpn-connect"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bot.handlers.tutorial_admin'`.

- [ ] **Step 4: Write the states**

```python
# app/bot/states/tutorial_admin.py
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TutorialAdminStates(StatesGroup):
    """One flow, three targets (stored in FSM data as `target`:
    "guide" | "profile" | "link"), rather than one state class per
    target - each target needs the same pick-protocol -> pick-platform
    -> await-content shape, just landing in a different table/config key
    at the end."""

    pick_protocol = State()
    pick_platform = State()
    await_content = State()
```

- [ ] **Step 5: Write the keyboards**

```python
# app/bot/keyboards/tutorial_admin.py
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.tutorial_platform import TutorialPlatform
from app.db.models.tutorial_protocol import TutorialProtocol


def tutorial_admin_root_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Upload a guide", callback_data="tutadm:guide")
    builder.button(text="📡 Upload an OpenVPN profile", callback_data="tutadm:profile")
    builder.button(text="📥 Set a download link", callback_data="tutadm:link")
    builder.adjust(1)
    return builder.as_markup()


def admin_protocol_keyboard(protocols: list[TutorialProtocol], *, target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for protocol in protocols:
        builder.button(text=protocol.label, callback_data=f"tutadm:{target}:protocol:{protocol.id}")
    builder.adjust(2)
    return builder.as_markup()


def admin_platform_keyboard(platforms: list[TutorialPlatform], *, target: str, allow_generic: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.button(text=platform.label, callback_data=f"tutadm:{target}:platform:{platform.id}")
    if allow_generic:
        builder.button(text="Generic (any platform)", callback_data=f"tutadm:{target}:platform:none")
    builder.adjust(2)
    return builder.as_markup()
```

- [ ] **Step 6: Write the handler**

```python
# app/bot/handlers/tutorial_admin.py
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.tutorial_admin import admin_platform_keyboard, admin_protocol_keyboard, tutorial_admin_root_keyboard
from app.bot.states.tutorial_admin import TutorialAdminStates
from app.db.session import async_session_maker
from app.services.admin_users import has_level
from app.services.app_config import set_config
from app.services.tutorials import list_platforms, list_protocols, upsert_guide, upsert_profile

router = Router(name="tutorial_admin")


async def _is_admin(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        return await has_level(session, telegram_id, "support")


@router.message(Command("admintutorials"))
async def admin_root_cmd(message: Message) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    await message.answer("📚 Tutorials & Profiles admin:", reply_markup=tutorial_admin_root_keyboard())


@router.callback_query(F.data.in_({"tutadm:guide", "tutadm:profile", "tutadm:link"}))
async def admin_pick_target_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    target = callback.data.split(":")[1]
    await state.set_state(TutorialAdminStates.pick_protocol)
    await state.update_data(target=target)
    async with async_session_maker() as session:
        protocols = await list_protocols(session)
    if callback.message is not None:
        await callback.message.edit_text("Pick a protocol:", reply_markup=admin_protocol_keyboard(protocols, target=target))
    await callback.answer()


@router.callback_query(TutorialAdminStates.pick_protocol, F.data.startswith("tutadm:"))
async def admin_pick_protocol_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, target, _kind, protocol_id_str = callback.data.split(":")
    protocol_id = int(protocol_id_str)
    await state.update_data(protocol_id=protocol_id)

    protocol_label = None
    async with async_session_maker() as session:
        from app.db.models.tutorial_protocol import TutorialProtocol

        protocol = await session.get(TutorialProtocol, protocol_id)
        protocol_label = protocol.label if protocol is not None else ""
        platforms = await list_platforms(session)

    # OpenVPN profiles/guides/links may be generic (no platform); L2TP
    # always needs a specific platform.
    allow_generic = protocol_label.strip().lower() == "openvpn"
    await state.set_state(TutorialAdminStates.pick_platform)
    if callback.message is not None:
        await callback.message.edit_text(
            "Pick a platform:", reply_markup=admin_platform_keyboard(platforms, target=target, allow_generic=allow_generic)
        )
    await callback.answer()


@router.callback_query(TutorialAdminStates.pick_platform, F.data.startswith("tutadm:"))
async def admin_pick_platform_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    platform_id_str = parts[-1]
    platform_id = None if platform_id_str == "none" else int(platform_id_str)
    await state.update_data(platform_id=platform_id)
    await state.set_state(TutorialAdminStates.await_content)
    if callback.message is not None:
        data = await state.get_data()
        prompt = "Send a URL:" if data["target"] == "link" else "Send a photo, document, or video:"
        await callback.message.edit_text(prompt)
    await callback.answer()


@router.message(TutorialAdminStates.await_content)
async def admin_receive_content(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not await _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    target, protocol_id, platform_id = data["target"], data["protocol_id"], data["platform_id"]
    await state.clear()

    if target == "link":
        url = (message.text or "").strip()
        async with async_session_maker() as session:
            from app.db.models.tutorial_platform import TutorialPlatform
            from app.db.models.tutorial_protocol import TutorialProtocol

            protocol = await session.get(TutorialProtocol, protocol_id)
            platform = await session.get(TutorialPlatform, platform_id) if platform_id is not None else None
            platform_key = platform.label.strip().lower() if platform is not None else "any"
            await set_config(session, f"download_link:{protocol.label.strip().lower()}:{platform_key}", url)
        await message.answer("✅ Download link saved.")
        return

    file_id: str | None = None
    file_type: str | None = None
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    elif message.document:
        file_id, file_type = message.document.file_id, "document"
    elif message.video:
        file_id, file_type = message.video.file_id, "video"

    async with async_session_maker() as session:
        if target == "guide":
            await upsert_guide(session, platform_id=platform_id, protocol_id=protocol_id, media_file_id=file_id, media_type=file_type)
        else:
            await upsert_profile(
                session, platform_id=platform_id, name=f"Profile {protocol_id}/{platform_id}",
                file_id=file_id, file_type=file_type, text=message.text if file_id is None else None,
            )
    await message.answer("✅ Saved.")
```

- [ ] **Step 7: Wire the router**

In `app/main.py`, add the import and registration in `build_dispatcher`:

```python
from app.bot.handlers import fallback, trial, tutorial_admin, users
```

```python
    dp.include_router(users.router)
    dp.include_router(trial.router)
    dp.include_router(tutorial_admin.router)
    dp.include_router(fallback.router)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `make test`
Expected: PASS — all tests in `test_tutorial_admin_flow.py`, plus the entire suite from Tasks 1-4 and the bootstrap/catalog work.

- [ ] **Step 9: Commit**

```bash
git add app/bot/states/tutorial_admin.py app/bot/keyboards/tutorial_admin.py app/bot/handlers/tutorial_admin.py \
        app/main.py tests/factories.py tests/functional/test_tutorial_admin_flow.py
git commit -m "feat: minimal admin flow for tutorial/profile/download-link content"
```

---

## What this plan deliberately does not build

Buy Subscription, Renew Service, My Services (including the still-open
IBSng credit-unit and data-usage risks), the payment abstraction, the
full admin panel (broadcast, discount codes, sales reports, general user/
service ops), and reminders all remain separate, later sub-projects per
the parent spec's own breakdown — none of them are needed for this
plan's trial flow to work and pass its own tests, and the delivery
service this plan builds (`tutorial_delivery.deliver_setup`) is written
to be reused unchanged by Buy/Renew when they land.
