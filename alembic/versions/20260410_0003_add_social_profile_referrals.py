"""add social profiles referrals and media assets

Revision ID: 20260410_0003
Revises: 20260408_0002
Create Date: 2026-04-10 18:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260410_0003"
down_revision = "20260408_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("variants_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_media_assets_owner_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
    )
    op.create_index("ix_media_assets_owner_user_id", "media_assets", ["owner_user_id"], unique=False)

    op.create_table(
        "player_public_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("bio", sa.String(length=500), nullable=True),
        sa.Column("status_text", sa.String(length=140), nullable=True),
        sa.Column("theme_mode", sa.String(length=32), nullable=False, server_default=sa.text("'default'")),
        sa.Column("accent_color", sa.String(length=7), nullable=True),
        sa.Column("avatar_asset_id", sa.Uuid(), nullable=True),
        sa.Column("banner_asset_id", sa.Uuid(), nullable=True),
        sa.Column("background_asset_id", sa.Uuid(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_followers_list_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_friends_list_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_profile_comments", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_player_public_profiles_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["avatar_asset_id"],
            ["media_assets.id"],
            name="fk_player_public_profiles_avatar_asset_id_media_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["banner_asset_id"],
            ["media_assets.id"],
            name="fk_player_public_profiles_banner_asset_id_media_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["background_asset_id"],
            ["media_assets.id"],
            name="fk_player_public_profiles_background_asset_id_media_assets",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_public_profiles"),
        sa.UniqueConstraint("user_id", name="uq_player_public_profiles_user_id"),
        sa.UniqueConstraint("slug", name="uq_player_public_profiles_slug"),
    )
    op.create_index("ix_player_public_profiles_slug", "player_public_profiles", ["slug"], unique=False)

    op.create_table(
        "player_follows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("follower_user_id", sa.Uuid(), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["follower_user_id"],
            ["users.id"],
            name="fk_player_follows_follower_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_player_follows_target_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_follows"),
        sa.UniqueConstraint("follower_user_id", "target_user_id", name="uq_player_follows_pair"),
        sa.CheckConstraint("follower_user_id <> target_user_id", name="ck_player_follows_no_self"),
    )
    op.create_index("ix_player_follows_follower_user_id", "player_follows", ["follower_user_id"], unique=False)
    op.create_index("ix_player_follows_target_user_id", "player_follows", ["target_user_id"], unique=False)

    op.create_table(
        "referral_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_referral_codes_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_referral_codes"),
        sa.UniqueConstraint("user_id", name="uq_referral_codes_user_id"),
        sa.UniqueConstraint("code", name="uq_referral_codes_code"),
    )
    op.create_index("ix_referral_codes_code", "referral_codes", ["code"], unique=False)

    op.create_table(
        "referral_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("inviter_user_id", sa.Uuid(), nullable=False),
        sa.Column("invited_user_id", sa.Uuid(), nullable=False),
        sa.Column("referral_code", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["inviter_user_id"],
            ["users.id"],
            name="fk_referral_links_inviter_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_user_id"],
            ["users.id"],
            name="fk_referral_links_invited_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_referral_links"),
        sa.UniqueConstraint("invited_user_id", name="uq_referral_links_invited_user_id"),
    )
    op.create_index("ix_referral_links_inviter_user_id", "referral_links", ["inviter_user_id"], unique=False)

    op.create_table(
        "referral_reward_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("referral_rank", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_qualified_referrals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reward_state", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_referral_reward_periods_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_referral_reward_periods"),
    )
    op.create_index("ix_referral_reward_periods_user_id", "referral_reward_periods", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_referral_reward_periods_user_id", table_name="referral_reward_periods")
    op.drop_table("referral_reward_periods")

    op.drop_index("ix_referral_links_inviter_user_id", table_name="referral_links")
    op.drop_table("referral_links")

    op.drop_index("ix_referral_codes_code", table_name="referral_codes")
    op.drop_table("referral_codes")

    op.drop_index("ix_player_follows_target_user_id", table_name="player_follows")
    op.drop_index("ix_player_follows_follower_user_id", table_name="player_follows")
    op.drop_table("player_follows")

    op.drop_index("ix_player_public_profiles_slug", table_name="player_public_profiles")
    op.drop_table("player_public_profiles")

    op.drop_index("ix_media_assets_owner_user_id", table_name="media_assets")
    op.drop_table("media_assets")