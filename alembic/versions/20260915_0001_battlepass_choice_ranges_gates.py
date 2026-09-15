"""battle pass: reward choice, random amounts, zone gates

* ``battlepass_rewards.count_max`` / ``amount_max`` — upper bound of a random amount
  (``count`` / ``amount`` stay the lower bound; NULL = fixed amount as before).
* ``battlepass_rewards.options`` — variants of a ``choice`` reward, the player picks one.
* ``battlepass_seasons.gates`` — zone boundaries: ``[{level, tier, label}]``, levels past
  ``level`` need the progression tier ``tier``.

Additive only: existing rows get NULL and behave exactly as before.

Revision ID: 20260915_0001
Revises: 20260914_0001
Create Date: 2026-09-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_0001"
down_revision = "20260914_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("battlepass_rewards", sa.Column("count_max", sa.Integer(), nullable=True))
    op.add_column("battlepass_rewards", sa.Column("amount_max", sa.BigInteger(), nullable=True))
    op.add_column("battlepass_rewards", sa.Column("options", postgresql.JSONB(), nullable=True))
    op.add_column("battlepass_seasons", sa.Column("gates", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("battlepass_seasons", "gates")
    op.drop_column("battlepass_rewards", "options")
    op.drop_column("battlepass_rewards", "amount_max")
    op.drop_column("battlepass_rewards", "count_max")
