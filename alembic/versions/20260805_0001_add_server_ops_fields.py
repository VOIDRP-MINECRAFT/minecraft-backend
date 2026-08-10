"""add server operations/monitoring fields to game_servers

Revision ID: 20260805_0001
Revises: 20260713_0003
Create Date: 2026-08-05

Adds the wiring the admin monitoring dashboard needs to observe & control each
game server: ``systemd_unit`` (→ MainPID / WorkingDirectory for CPU/RAM/disk),
optional ``data_dir`` / ``log_path`` overrides, and per-server RCON connection
(``rcon_host`` / ``rcon_port`` / ``rcon_password``) for the live console, TPS,
player list and moderation. All nullable; unconfigured servers just show
"not configured" in the panel.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260805_0001"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("systemd_unit", sa.String(length=128), nullable=True))
    op.add_column("game_servers", sa.Column("data_dir", sa.String(length=512), nullable=True))
    op.add_column("game_servers", sa.Column("log_path", sa.String(length=512), nullable=True))
    op.add_column("game_servers", sa.Column("rcon_host", sa.String(length=255), nullable=True))
    op.add_column("game_servers", sa.Column("rcon_port", sa.Integer(), nullable=True))
    op.add_column("game_servers", sa.Column("rcon_password", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("game_servers", "rcon_password")
    op.drop_column("game_servers", "rcon_port")
    op.drop_column("game_servers", "rcon_host")
    op.drop_column("game_servers", "log_path")
    op.drop_column("game_servers", "data_dir")
    op.drop_column("game_servers", "systemd_unit")
