from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, UuidPrimaryKeyMixin


class AdminAuditLog(UuidPrimaryKeyMixin, Base):
    """Append-only record of a staff action in the admin panel.

    Written by :func:`apps.api.app.core.audit.record_audit` from the action
    endpoints. The actor's user id *and* a denormalized name are stored so the
    row survives even if the user is later renamed or deleted. ``server_id`` is
    nullable because some actions are global (moderator grants, player edits).
    """

    __tablename__ = "admin_audit_log"

    # Who — nullable so an X-Admin-Api-Secret / system action can still log.
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_name: Mapped[str] = mapped_column(String(120), nullable=False, default="system")

    # What — ``category`` groups actions for filtering (e.g. "monitoring",
    # "punishment", "anticheat", "news"), ``action`` is the specific verb.
    category: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    # On whom / what — free-form so any target type fits.
    target_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    target_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Where — the server the action applied to, if any.
    server_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("game_servers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Extra structured context (before/after, command text, reason, ...).
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
