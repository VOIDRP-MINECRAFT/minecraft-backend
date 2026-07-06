"""scope game data by server_id

Revision ID: 20260706_0002
Revises: 20260706_0001
Create Date: 2026-07-06

Adds server_id (FK -> game_servers, ON DELETE CASCADE) to all per-server
game-data tables, backfills existing rows to the default server, then makes
the column NOT NULL. Swaps former global-unique keys to composite
(server_id, ...) keys.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '20260706_0002'
down_revision = '20260706_0001'
branch_labels = None
depends_on = None

# All per-server tables getting a server_id column.
PER_SERVER_TABLES = [
    "nations",
    "nation_members",
    "nation_stats",
    "nation_treasury_transactions",
    "nation_activity_logs",
    "nation_join_requests",
    "nation_member_stat_snapshots",
    "nation_market_listings",
    "nation_market_orders",
    "alliances",
    "alliance_members",
    "alliance_proposals",
    "alliance_votes",
    "economy_market_items",
    "price_history_snapshots",
    "economy_shop_transactions",
    "player_market_sell_orders",
    "player_market_buy_orders",
    "player_market_trades",
    "player_market_pending_deliveries",
    "player_market_web_actions",
    "player_stat_cache",
    "player_progressions",
    "play_tickets",
    "battlepass_premium",
    "battlepass_progress",
    "anticheat_violations",
    "anticheat_mod_snapshots",
    "anticheat_injection_reports",
    "referral_reward_periods",
]


def upgrade() -> None:
    conn = op.get_bind()
    default_id = conn.execute(
        sa.text(
            "SELECT id FROM game_servers WHERE is_default = true "
            "ORDER BY sort_order LIMIT 1"
        )
    ).scalar()
    if default_id is None:
        raise RuntimeError("No default game_servers row found; run 20260706_0001 first")

    for table in PER_SERVER_TABLES:
        op.add_column(table, sa.Column("server_id", sa.Uuid(), nullable=True))
        conn.execute(
            sa.text(f"UPDATE {table} SET server_id = :sid").bindparams(sid=default_id)
        )
        op.alter_column(table, "server_id", existing_type=sa.Uuid(), nullable=False)
        op.create_index(f"ix_{table}_server_id", table, ["server_id"])
        op.create_foreign_key(
            f"fk_{table}_server_id_game_servers",
            table,
            "game_servers",
            ["server_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # ── Uniqueness swaps: former global-unique -> (server_id, X) ────────────
    # nations.slug / alliances.slug were enforced by a UNIQUE index.
    for table in ("nations", "alliances"):
        op.drop_index(f"ix_{table}_slug", table_name=table)
        op.create_index(f"ix_{table}_slug", table, ["slug"])  # non-unique now
        op.create_unique_constraint(
            f"uq_{table}_server_slug", table, ["server_id", "slug"]
        )

    # The rest were enforced by UNIQUE constraints (plain indexes already exist).
    op.drop_constraint(
        "uq_economy_market_items_material", "economy_market_items", type_="unique"
    )
    op.create_unique_constraint(
        "uq_economy_market_items_server_material",
        "economy_market_items",
        ["server_id", "material"],
    )

    op.drop_constraint(
        "uq_player_stat_cache_nickname_normalized", "player_stat_cache", type_="unique"
    )
    op.create_unique_constraint(
        "uq_player_stat_cache_server_nick",
        "player_stat_cache",
        ["server_id", "minecraft_nickname_normalized"],
    )

    op.drop_constraint(
        "uq_battlepass_premium_minecraft_uuid", "battlepass_premium", type_="unique"
    )
    op.create_unique_constraint(
        "uq_battlepass_premium_server_uuid",
        "battlepass_premium",
        ["server_id", "minecraft_uuid"],
    )

    op.drop_constraint(
        "uq_battlepass_progress_minecraft_uuid", "battlepass_progress", type_="unique"
    )
    op.create_unique_constraint(
        "uq_battlepass_progress_server_uuid",
        "battlepass_progress",
        ["server_id", "minecraft_uuid"],
    )

    op.drop_constraint(
        "uq_player_progression_tier", "player_progressions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_player_progression_tier",
        "player_progressions",
        ["server_id", "minecraft_nickname_normalized", "tier_name"],
    )


def downgrade() -> None:
    # Reverse uniqueness swaps.
    op.drop_constraint("uq_player_progression_tier", "player_progressions", type_="unique")
    op.create_unique_constraint(
        "uq_player_progression_tier",
        "player_progressions",
        ["minecraft_nickname_normalized", "tier_name"],
    )
    op.drop_constraint("uq_battlepass_progress_server_uuid", "battlepass_progress", type_="unique")
    op.create_unique_constraint(
        "uq_battlepass_progress_minecraft_uuid", "battlepass_progress", ["minecraft_uuid"]
    )
    op.drop_constraint("uq_battlepass_premium_server_uuid", "battlepass_premium", type_="unique")
    op.create_unique_constraint(
        "uq_battlepass_premium_minecraft_uuid", "battlepass_premium", ["minecraft_uuid"]
    )
    op.drop_constraint("uq_player_stat_cache_server_nick", "player_stat_cache", type_="unique")
    op.create_unique_constraint(
        "uq_player_stat_cache_nickname_normalized",
        "player_stat_cache",
        ["minecraft_nickname_normalized"],
    )
    op.drop_constraint(
        "uq_economy_market_items_server_material", "economy_market_items", type_="unique"
    )
    op.create_unique_constraint(
        "uq_economy_market_items_material", "economy_market_items", ["material"]
    )
    for table in ("nations", "alliances"):
        op.drop_constraint(f"uq_{table}_server_slug", table, type_="unique")
        op.drop_index(f"ix_{table}_slug", table_name=table)
        op.create_index(f"ix_{table}_slug", table, ["slug"], unique=True)

    for table in reversed(PER_SERVER_TABLES):
        op.drop_constraint(f"fk_{table}_server_id_game_servers", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_server_id", table_name=table)
        op.drop_column(table, "server_id")
