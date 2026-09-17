"""travelling trader: settings, catalog, visits, stock, sessions, transactions

New tables only; nothing existing changes.

Revision ID: 20260917_0002
Revises: 20260917_0001
Create Date: 2026-09-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_0002"
down_revision = "20260917_0001"
branch_labels = None
depends_on = None


def _server_fk():
    return sa.Column("server_id", sa.Uuid(), sa.ForeignKey("game_servers.id", ondelete="CASCADE"), nullable=False, index=True)


def upgrade() -> None:
    op.create_table(
        "trader_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("mid_unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", name="uq_trader_settings_server"),
    )
    op.create_table(
        "trader_catalog_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("item_key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("rarity", sa.SmallInteger(), nullable=False),
        sa.Column("phase", sa.String(8), nullable=False),
        sa.Column("unit_value", sa.Float(), nullable=False),
        sa.Column("can_buy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_sell", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("qty_min", sa.Integer(), nullable=True),
        sa.Column("qty_max", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", "item_key", name="uq_trader_catalog_server_item"),
    )
    op.create_table(
        "trader_visits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("phases", sa.String(32), nullable=False),
        sa.Column("payout_budget", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(16), nullable=False, server_default="schedule"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("announced_soon_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("server_id", "starts_at", name="uq_trader_visits_server_start"),
    )
    op.create_table(
        "trader_stock",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("visit_id", sa.Uuid(), sa.ForeignKey("trader_visits.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), sa.ForeignKey("trader_catalog_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("rarity", sa.SmallInteger(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("qty_total", sa.Integer(), nullable=False),
        sa.Column("qty_left", sa.Integer(), nullable=False),
        sa.UniqueConstraint("visit_id", "side", "slot", name="uq_trader_stock_visit_side_slot"),
    )
    op.create_table(
        "trader_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("visit_id", sa.Uuid(), sa.ForeignKey("trader_visits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_name", sa.String(16), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "trader_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _server_fk(),
        sa.Column("visit_id", sa.Uuid(), sa.ForeignKey("trader_visits.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stock_id", sa.Uuid(), sa.ForeignKey("trader_stock.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("player_name", sa.String(16), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("item_key", sa.String(128), nullable=False),
        sa.Column("qty_requested", sa.Integer(), nullable=False),
        sa.Column("qty_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("web_action_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    for name in ("trader_transactions", "trader_sessions", "trader_stock", "trader_visits", "trader_catalog_items", "trader_settings"):
        op.drop_table(name)
