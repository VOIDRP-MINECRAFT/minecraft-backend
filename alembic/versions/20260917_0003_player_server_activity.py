"""player server activity + registration source

Tracks which servers an account actually plays on and whether it connects through our
launcher or a third-party client, so the admin player list can show it. Also records
where an account was registered (site form or the in-game window).

Revision ID: 20260917_0003
Revises: 20260917_0002
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260917_0003"
down_revision = "20260917_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_server_activity",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_client", sa.String(length=16), nullable=False),
        sa.Column("launcher_logins", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("external_logins", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["server_id"], ["game_servers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "server_id", name="uq_player_server_activity"),
    )
    op.create_index("ix_player_server_activity_user_id", "player_server_activity", ["user_id"])
    op.create_index("ix_player_server_activity_server_id", "player_server_activity", ["server_id"])

    op.add_column("player_accounts", sa.Column("registration_source", sa.String(length=16), nullable=True))
    op.add_column("player_accounts", sa.Column("registration_server_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_player_accounts_registration_server",
        "player_accounts",
        "game_servers",
        ["registration_server_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Everything that exists today was created through the site form.
    op.execute("UPDATE player_accounts SET registration_source = 'site' WHERE registration_source IS NULL")

    # Seed activity from consumed play tickets: those are launcher logins, and they
    # already carry the server, so history is not lost.
    op.execute(
        """
        INSERT INTO player_server_activity
            (id, user_id, server_id, first_seen_at, last_seen_at, last_client, launcher_logins, external_logins)
        SELECT
            gen_random_uuid(),
            t.user_id,
            t.server_id,
            MIN(t.consumed_at),
            MAX(t.consumed_at),
            'launcher',
            COUNT(*),
            0
        FROM play_tickets t
        WHERE t.consumed_at IS NOT NULL
        GROUP BY t.user_id, t.server_id
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_player_accounts_registration_server", "player_accounts", type_="foreignkey")
    op.drop_column("player_accounts", "registration_server_id")
    op.drop_column("player_accounts", "registration_source")
    op.drop_index("ix_player_server_activity_server_id", table_name="player_server_activity")
    op.drop_index("ix_player_server_activity_user_id", table_name="player_server_activity")
    op.drop_table("player_server_activity")
