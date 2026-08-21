"""create voxel_games

Revision ID: 20260821_0001
Revises: 20260811_0002
Create Date: 2026-08-21

Voxel Engine — Этап 1: канал backend↔мод. Таблица определений игр, авторимых
на платформе и вытягиваемых модом. ``definition`` — плоский JSON игры (тот же
контракт, что читает GameLoader). ``version`` растёт при каждой правке (мод
сравнивает и hot-reload'ит). Обратный канал — колонки ``last_report_*``.
Server-scoped: FK на game_servers, уникальность (server_id, game_id).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260821_0001"
down_revision = "20260811_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voxel_games",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_report_status", sa.String(length=16), nullable=True),
        sa.Column("last_report_message", sa.Text(), nullable=True),
        sa.Column("last_reported_version", sa.Integer(), nullable=True),
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"], ["game_servers.id"],
            name="fk_voxel_games_server_id_game_servers", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_voxel_games"),
        sa.UniqueConstraint("server_id", "game_id", name="uq_voxel_games_server_game_id"),
    )
    op.create_index("ix_voxel_games_server_id", "voxel_games", ["server_id"])
    op.create_index("ix_voxel_games_game_id", "voxel_games", ["game_id"])


def downgrade() -> None:
    op.drop_index("ix_voxel_games_game_id", table_name="voxel_games")
    op.drop_index("ix_voxel_games_server_id", table_name="voxel_games")
    op.drop_table("voxel_games")
