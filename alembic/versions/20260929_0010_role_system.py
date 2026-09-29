"""roles like in Discord, and admins of single servers

``staff_roles``: a named, coloured bundle of permissions at a place in the list
(``position``, higher = more senior). ``server_ids`` null → the role applies on every
server and may hold platform keys; a list → only per-server keys, on those servers.
``staff_role_members`` links people to roles.

``users.admin_server_ids``: servers on which the person is an admin — every per-server
permission there, and managing staff and roles of those servers. Additive only.

Revision ID: 20260929_0010
Revises: 20260929_0009
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_0010"
down_revision = "20260929_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("admin_server_ids", postgresql.JSONB(), nullable=False,
                                     server_default=sa.text("'[]'::jsonb")))
    op.create_table(
        "staff_roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(48), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#99aab5"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("server_ids", postgresql.JSONB(), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "staff_role_members",
        sa.Column("role_id", sa.Uuid(), sa.ForeignKey("staff_roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_staff_role_members_user_id", "staff_role_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_staff_role_members_user_id", table_name="staff_role_members")
    op.drop_table("staff_role_members")
    op.drop_table("staff_roles")
    op.drop_column("users", "admin_server_ids")
