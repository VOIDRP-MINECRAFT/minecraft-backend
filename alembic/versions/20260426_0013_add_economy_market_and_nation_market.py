"""add economy market and nation market

Revision ID: 20260426_0013
Revises: 20260423_0012
Create Date: 2026-04-26 22:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260426_0013"
down_revision = "20260423_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "economy_market_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("material", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("group_key", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("base_buy_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("base_sell_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("current_buy_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("current_sell_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("buy_multiplier", sa.Numeric(12, 6), nullable=False, server_default="1"),
        sa.Column("sell_multiplier", sa.Numeric(12, 6), nullable=False, server_default="1"),
        sa.Column("demand_score", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("supply_score", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material", name="uq_economy_market_items_material"),
    )
    op.create_index("ix_economy_market_items_material", "economy_market_items", ["material"], unique=False)
    op.create_index("ix_economy_market_items_enabled", "economy_market_items", ["enabled"], unique=False)

    op.create_table(
        "economy_shop_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_name", sa.String(length=16), nullable=False),
        sa.Column("material", sa.String(length=96), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("base_total_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("final_total_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("market_multiplier", sa.Numeric(12, 6), nullable=False, server_default="1"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_economy_shop_transactions_material", "economy_shop_transactions", ["material"], unique=False)
    op.create_index("ix_economy_shop_transactions_created_at", "economy_shop_transactions", ["created_at"], unique=False)

    op.create_table(
        "nation_market_listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("seller_player_name", sa.String(length=16), nullable=False),
        sa.Column("seller_role", sa.String(length=16), nullable=False),
        sa.Column("material", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("item_stack_base64", sa.Text(), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("remaining_amount", sa.Integer(), nullable=False),
        sa.Column("sold_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("anchor_unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("market_price_at_create", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("relative_price_multiplier", sa.Numeric(12, 6), nullable=False, server_default="1"),
        sa.Column("current_unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("min_unit_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("max_unit_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("pricing_mode", sa.String(length=32), nullable=False, server_default="relative_to_market"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sold_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nation_market_listings_nation_id", "nation_market_listings", ["nation_id"], unique=False)
    op.create_index("ix_nation_market_listings_material", "nation_market_listings", ["material"], unique=False)
    op.create_index("ix_nation_market_listings_status", "nation_market_listings", ["status"], unique=False)
    op.create_index("ix_nation_market_listings_created_at", "nation_market_listings", ["created_at"], unique=False)

    op.create_table(
        "nation_market_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_player_name", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("fee_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["nation_market_listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nation_market_orders_listing_id", "nation_market_orders", ["listing_id"], unique=False)
    op.create_index("ix_nation_market_orders_nation_id", "nation_market_orders", ["nation_id"], unique=False)
    op.create_index("ix_nation_market_orders_created_at", "nation_market_orders", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_nation_market_orders_created_at", table_name="nation_market_orders")
    op.drop_index("ix_nation_market_orders_nation_id", table_name="nation_market_orders")
    op.drop_index("ix_nation_market_orders_listing_id", table_name="nation_market_orders")
    op.drop_table("nation_market_orders")

    op.drop_index("ix_nation_market_listings_created_at", table_name="nation_market_listings")
    op.drop_index("ix_nation_market_listings_status", table_name="nation_market_listings")
    op.drop_index("ix_nation_market_listings_material", table_name="nation_market_listings")
    op.drop_index("ix_nation_market_listings_nation_id", table_name="nation_market_listings")
    op.drop_table("nation_market_listings")

    op.drop_index("ix_economy_shop_transactions_created_at", table_name="economy_shop_transactions")
    op.drop_index("ix_economy_shop_transactions_material", table_name="economy_shop_transactions")
    op.drop_table("economy_shop_transactions")

    op.drop_index("ix_economy_market_items_enabled", table_name="economy_market_items")
    op.drop_index("ix_economy_market_items_material", table_name="economy_market_items")
    op.drop_table("economy_market_items")
