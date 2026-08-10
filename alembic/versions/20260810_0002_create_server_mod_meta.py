"""create server_mod_meta (per-server mod classification override)

Revision ID: 20260810_0002
Revises: 20260810_0001
Create Date: 2026-08-10

Backs the admin "Моды" panel: admin-editable optional/required flags + display
name/description for each mod jar, keyed by (server_id, filename). The manifest
generator reads these as an override over its hardcoded classification dicts.
Purely additive — no existing data touched.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260810_0002"
down_revision = "20260810_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_mod_meta",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("optional", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"], ["game_servers.id"],
            name=op.f("fk_server_mod_meta_server_id_game_servers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_server_mod_meta")),
        sa.UniqueConstraint("server_id", "filename", name="uq_server_mod_meta_server_filename"),
    )
    op.create_index(op.f("ix_server_mod_meta_server_id"), "server_mod_meta", ["server_id"], unique=False)
    op.create_index(op.f("ix_server_mod_meta_filename"), "server_mod_meta", ["filename"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_server_mod_meta_filename"), table_name="server_mod_meta")
    op.drop_index(op.f("ix_server_mod_meta_server_id"), table_name="server_mod_meta")
    op.drop_table("server_mod_meta")
