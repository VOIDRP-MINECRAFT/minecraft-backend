"""play_tickets.issued_ip

The plugin servers have no mod that could carry a ticket into the handshake, so a
launcher player is recognised by matching the nickname and the address the ticket was
issued to. Storing the issuing IP is what makes that match meaningful.

Revision ID: 20260918_0001
Revises: 20260917_0003
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260918_0001"
down_revision = "20260917_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("play_tickets", sa.Column("issued_ip", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("play_tickets", "issued_ip")
