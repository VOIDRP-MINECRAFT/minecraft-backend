"""play_tickets.hostname_label

A vanilla client carries nothing but the address it dialled, so the launcher puts a
short label in front of the server's hostname and the plugin reads it from the
handshake. The ticket itself is 64 url-safe characters — too long for a DNS label and
containing characters a resolver rejects — hence a separate 24-character hex label.

Revision ID: 20260918_0002
Revises: 20260918_0001
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260918_0002"
down_revision = "20260918_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("play_tickets", sa.Column("hostname_label", sa.String(length=32), nullable=True))
    op.create_index("ix_play_tickets_hostname_label", "play_tickets", ["hostname_label"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_play_tickets_hostname_label", table_name="play_tickets")
    op.drop_column("play_tickets", "hostname_label")
