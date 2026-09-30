"""game_servers.ticket_hostname: the launcher carries the play ticket in the connect address

The launcher used to prefix "<label>." to the host of every server whose client pack is
vanilla/paper. That needs a wildcard DNS record for the server's domain; a partner server
without one could not be reached at all. Now it is a per-server switch. It stays on where it
was in effect — our own plugin servers — and off everywhere else (login by nickname + IP
works without it).

Revision ID: 20260930_0008
Revises: 20260930_0007
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260930_0008"
down_revision = "20260930_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_servers", sa.Column("ticket_hostname", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.get_bind().execute(sa.text(
        "update game_servers set ticket_hostname = true "
        "where not is_external and lower(loader) in ('vanilla', 'paper')"
    ))


def downgrade() -> None:
    op.drop_column("game_servers", "ticket_hostname")
