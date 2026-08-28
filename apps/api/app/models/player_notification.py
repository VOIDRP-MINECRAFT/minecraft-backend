from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, TimestampMixin, UuidPrimaryKeyMixin


class PlayerNotification(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    """A reactive per-account in-game notification (shown in the HUD overlay).

    Produced by account events (battle pass award, nation join request, alliance
    vote, season reward, …) — from the backend directly or pushed by a plugin via
    the game-sync endpoint. Consumed by the WebGUI HUD which polls the webgui
    endpoint, slides new cards in on the right, and dismisses them.
    """

    __tablename__ = "player_notifications"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(String(400), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(48), nullable=True)     # GuiIcon name or item id
    accent: Mapped[str | None] = mapped_column(String(16), nullable=True)   # violet | gold | green | red | blue
    action_type: Mapped[str | None] = mapped_column(String(24), nullable=True)   # route | command
    action_payload: Mapped[str | None] = mapped_column(String(200), nullable=True)
    action_label: Mapped[str | None] = mapped_column(String(48), nullable=True)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
