"""add nations foundation

Revision ID: 20260410_0004
Revises: 20260410_0003
Create Date: 2026-04-10 20:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260410_0004"
down_revision = "20260410_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("tag", sa.String(length=8), nullable=False),
        sa.Column("short_description", sa.String(length=140), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("accent_color", sa.String(length=7), nullable=True),
        sa.Column("recruitment_policy", sa.String(length=16), nullable=False, server_default="request"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("leader_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("icon_url", sa.String(length=512), nullable=True),
        sa.Column("icon_preview_url", sa.String(length=512), nullable=True),
        sa.Column("banner_url", sa.String(length=512), nullable=True),
        sa.Column("banner_preview_url", sa.String(length=512), nullable=True),
        sa.Column("background_url", sa.String(length=512), nullable=True),
        sa.Column("background_preview_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["leader_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nations_slug", "nations", ["slug"], unique=True)
    op.create_index("ix_nations_leader_user_id", "nations", ["leader_user_id"], unique=False)
    op.create_index("ix_nations_created_by_user_id", "nations", ["created_by_user_id"], unique=False)

    op.create_table(
        "nation_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nation_id", "user_id", name="uq_nation_members_nation_user"),
    )
    op.create_index("ix_nation_members_nation_id", "nation_members", ["nation_id"], unique=False)
    op.create_index("ix_nation_members_user_id", "nation_members", ["user_id"], unique=False)

    op.create_table(
        "nation_join_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["nation_id"], ["nations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nation_id", "user_id", name="uq_nation_join_requests_nation_user"),
    )
    op.create_index("ix_nation_join_requests_nation_id", "nation_join_requests", ["nation_id"], unique=False)
    op.create_index("ix_nation_join_requests_user_id", "nation_join_requests", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_nation_join_requests_user_id", table_name="nation_join_requests")
    op.drop_index("ix_nation_join_requests_nation_id", table_name="nation_join_requests")
    op.drop_table("nation_join_requests")

    op.drop_index("ix_nation_members_user_id", table_name="nation_members")
    op.drop_index("ix_nation_members_nation_id", table_name="nation_members")
    op.drop_table("nation_members")

    op.drop_index("ix_nations_created_by_user_id", table_name="nations")
    op.drop_index("ix_nations_leader_user_id", table_name="nations")
    op.drop_index("ix_nations_slug", table_name="nations")
    op.drop_table("nations")
