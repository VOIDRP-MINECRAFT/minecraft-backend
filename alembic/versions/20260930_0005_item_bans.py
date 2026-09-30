"""banned items managed from the admin panel, per server

* ``banned_items`` — the list per server (item, reason, on/off, who and when);
* ``server_items`` — what a server's plugin reported: its item registry, when it last took
  the list, the plugin version;
* ``game_servers.item_ban_settings`` — message to the player and scan period.

The two items that were in the main server's GameSync ``config.yml`` move into the default
server's list.

Revision ID: 20260930_0005
Revises: 20260930_0004
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0005"
down_revision = "20260930_0004"
branch_labels = None
depends_on = None

_FROM_CONFIG = [
    ("reliquary:rod_of_lyssa", "Удочка Лиссы: ворует предметы из чужих инвентарей"),
    ("relics:infinity_ham", "Бесконечный окорок: обесценивает голод и выживание"),
]


def upgrade() -> None:
    op.create_table(
        "banned_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", "item_id", name="uq_banned_items_server_item"),
    )
    op.create_index("ix_banned_items_server_id", "banned_items", ["server_id"])
    op.create_table(
        "server_items",
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("item_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("items_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bans_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plugin_version", sa.String(32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "game_servers",
        sa.Column("item_ban_settings", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    bind = op.get_bind()
    default_id = bind.execute(sa.text("select id from game_servers where is_default limit 1")).scalar()
    if default_id is not None:
        for item_id, reason in _FROM_CONFIG:
            bind.execute(
                sa.text(
                    "insert into banned_items (id, server_id, item_id, reason, enabled, created_by) "
                    "values (gen_random_uuid(), :sid, :item, :reason, true, 'config.yml')"
                ),
                {"sid": default_id, "item": item_id, "reason": reason},
            )


def downgrade() -> None:
    op.drop_column("game_servers", "item_ban_settings")
    op.drop_table("server_items")
    op.drop_index("ix_banned_items_server_id", table_name="banned_items")
    op.drop_table("banned_items")
