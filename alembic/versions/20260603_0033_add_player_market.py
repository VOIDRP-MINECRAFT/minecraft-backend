"""add player market orders tables

Revision ID: 20260603_0033
Revises: 20260602_0032
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "20260603_0033"
down_revision = "20260602_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_market_sell_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("seller_player_name", sa.String(16), nullable=False),
        sa.Column("item_key", sa.String(192), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("item_stack_base64", sa.Text(), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("remaining_amount", sa.Integer(), nullable=False),
        sa.Column("filled_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("remaining_amount >= 0", name="ck_player_market_sell_orders_remaining_amount"),
        sa.CheckConstraint("unit_price > 0", name="ck_player_market_sell_orders_unit_price"),
    )
    op.create_index("ix_player_market_sell_orders_seller_player_name", "player_market_sell_orders", ["seller_player_name"])
    op.create_index("ix_player_market_sell_orders_item_key", "player_market_sell_orders", ["item_key"])
    op.create_index("ix_player_market_sell_orders_status", "player_market_sell_orders", ["status"])
    op.create_index("ix_player_market_sell_orders_expires_at", "player_market_sell_orders", ["expires_at"])
    op.create_index("ix_player_market_sell_orders_item_key_status", "player_market_sell_orders", ["item_key", "status"])

    op.create_table(
        "player_market_buy_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("buyer_player_name", sa.String(16), nullable=False),
        sa.Column("item_key", sa.String(192), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("remaining_amount", sa.Integer(), nullable=False),
        sa.Column("filled_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("reserved_funds", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("remaining_amount >= 0", name="ck_player_market_buy_orders_remaining_amount"),
        sa.CheckConstraint("unit_price > 0", name="ck_player_market_buy_orders_unit_price"),
    )
    op.create_index("ix_player_market_buy_orders_buyer_player_name", "player_market_buy_orders", ["buyer_player_name"])
    op.create_index("ix_player_market_buy_orders_item_key", "player_market_buy_orders", ["item_key"])
    op.create_index("ix_player_market_buy_orders_status", "player_market_buy_orders", ["status"])
    op.create_index("ix_player_market_buy_orders_expires_at", "player_market_buy_orders", ["expires_at"])
    op.create_index("ix_player_market_buy_orders_item_key_status", "player_market_buy_orders", ["item_key", "status"])

    op.create_table(
        "player_market_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("sell_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("player_market_sell_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("buy_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("player_market_buy_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("seller_player_name", sa.String(16), nullable=False),
        sa.Column("buyer_player_name", sa.String(16), nullable=False),
        sa.Column("item_key", sa.String(192), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("fee_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_seller_proceeds", sa.Numeric(18, 2), nullable=False),
        sa.Column("item_stack_base64", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_player_market_trades_sell_order_id", "player_market_trades", ["sell_order_id"])
    op.create_index("ix_player_market_trades_buy_order_id", "player_market_trades", ["buy_order_id"])
    op.create_index("ix_player_market_trades_seller_player_name", "player_market_trades", ["seller_player_name"])
    op.create_index("ix_player_market_trades_buyer_player_name", "player_market_trades", ["buyer_player_name"])
    op.create_index("ix_player_market_trades_item_key", "player_market_trades", ["item_key"])
    op.create_index("ix_player_market_trades_created_at", "player_market_trades", ["created_at"])

    op.create_table(
        "player_market_pending_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("player_name", sa.String(16), nullable=False),
        sa.Column("delivery_type", sa.String(32), nullable=False),
        sa.Column("trade_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("player_market_trades.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sell_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("player_market_sell_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("buy_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("player_market_buy_orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount_money", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("amount_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("item_stack_base64", sa.Text(), nullable=True),
        sa.Column("item_key", sa.String(192), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_player_market_pending_deliveries_player_name", "player_market_pending_deliveries", ["player_name"])
    op.create_index("ix_player_market_pending_deliveries_delivered", "player_market_pending_deliveries", ["delivered"])
    op.create_index("ix_player_market_pending_deliveries_created_at", "player_market_pending_deliveries", ["created_at"])


def downgrade() -> None:
    op.drop_table("player_market_pending_deliveries")
    op.drop_table("player_market_trades")
    op.drop_table("player_market_buy_orders")
    op.drop_table("player_market_sell_orders")
