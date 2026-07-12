"""switch claims from full-height chunk squares to 16x16x16 cube volumes

Revision ID: 20260709_0002
Revises: 20260709_0001
Create Date: 2026-07-09

A claim is now a set of 16x16x16 cube cells (cube = floor(coord/16) on each axis,
i.e. a chunk section). ``cubes`` holds the list of [cx, cy, cz] cells; ``level``
is the cube count. Existing claims are backfilled with the single cube around
their core. The old (server, dim, core_chunk) unique constraint is dropped —
overlap is now enforced per-cube in the service/mod.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260709_0002"
down_revision = "20260709_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("cubes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
    )
    # Cubes are relative offsets from the core cube; the core cube is [0, 0, 0]
    # (a 16x16x16 volume centred on the core). Backfill existing claims to that.
    op.execute("UPDATE claims SET cubes = '[[0, 0, 0]]'::jsonb, level = 1")
    op.drop_constraint("uq_claims_server_dim_chunk", "claims", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_claims_server_dim_chunk", "claims",
        ["server_id", "dimension", "core_chunk_x", "core_chunk_z"],
    )
    op.drop_column("claims", "cubes")
