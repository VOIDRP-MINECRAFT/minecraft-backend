"""player_market_buy_order_display_icon

Revision ID: 20260603_0034
Revises: 20260603_0033
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa

revision = "20260603_0034"
down_revision = "20260603_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "player_market_buy_orders",
        sa.Column("item_display_base64", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("player_market_buy_orders", "item_display_base64")
