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
