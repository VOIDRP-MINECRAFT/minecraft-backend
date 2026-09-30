"""in-game permissions (LuckPerms) managed from the admin panel

* ``game_perm_catalogs`` — per server: groups, their nodes and members, the plugins'
  permissions, as the VoidRpPerms plugin last reported them;
* ``game_perm_ops`` — changes queued for the plugin and their results;
* ``game_perm_direct`` — a group given to a person directly in the panel;
* ``game_perm_applied`` — what the panel has put on people in LuckPerms (so it takes away
  only its own);
* ``game_perm_flags`` — groups only the owner hands out or edits;
* ``staff_roles.game_groups`` — the LuckPerms groups a role gives, per server.

Revision ID: 20260930_0003
Revises: 20260930_0002
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0003"
down_revision = "20260930_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_perm_catalogs",
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("plugin_version", sa.String(32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "game_perm_ops",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("op", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_game_perm_ops_server_status", "game_perm_ops", ["server_id", "status"])
    for name in ("game_perm_direct", "game_perm_applied"):
        op.create_table(
            name,
            sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("group_name", sa.String(64), primary_key=True),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    op.create_table(
        "game_perm_flags",
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("group_name", sa.String(64), primary_key=True),
        sa.Column("owner_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("staff_roles", sa.Column("game_groups", postgresql.JSONB(), nullable=False,
                                           server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("staff_roles", "game_groups")
    for name in ("game_perm_flags", "game_perm_applied", "game_perm_direct"):
        op.drop_table(name)
    op.drop_index("ix_game_perm_ops_server_status", table_name="game_perm_ops")
    op.drop_table("game_perm_ops")
    op.drop_table("game_perm_catalogs")
