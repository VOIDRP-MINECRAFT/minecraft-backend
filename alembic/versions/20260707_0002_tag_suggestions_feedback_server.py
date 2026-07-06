"""tag mod_suggestions and player_feedback with originating server

Revision ID: 20260707_0002
Revises: 20260707_0001
Create Date: 2026-07-07

Adds a nullable ``server_id`` FK to ``mod_suggestions`` and ``player_feedback``
so submissions record which server they came from. Nullable + ON DELETE SET NULL
because these tables are otherwise global (legacy rows have no server).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260707_0002"
down_revision = "20260707_0001"
branch_labels = None
depends_on = None


def _add(table: str) -> None:
    op.add_column(table, sa.Column("server_id", sa.Uuid(), nullable=True))
    op.create_index(op.f(f"ix_{table}_server_id"), table, ["server_id"])
    op.create_foreign_key(
        op.f(f"fk_{table}_server_id_game_servers"),
        table,
        "game_servers",
        ["server_id"],
        ["id"],
        ondelete="SET NULL",
    )


def _drop(table: str) -> None:
    op.drop_constraint(op.f(f"fk_{table}_server_id_game_servers"), table, type_="foreignkey")
    op.drop_index(op.f(f"ix_{table}_server_id"), table_name=table)
    op.drop_column(table, "server_id")


def upgrade() -> None:
    _add("mod_suggestions")
    _add("player_feedback")


def downgrade() -> None:
    _drop("player_feedback")
    _drop("mod_suggestions")
