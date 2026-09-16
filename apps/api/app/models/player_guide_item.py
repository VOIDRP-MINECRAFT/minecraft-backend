"""Key progression items a player has held — drives the in-game roadmap ("путеводитель").

The GameSync plugin scans online inventories for the item ids listed in
``core/progression_roadmap.json`` and reports each one the first time it shows up.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, ServerScopedMixin, UuidPrimaryKeyMixin


class PlayerGuideItem(UuidPrimaryKeyMixin, ServerScopedMixin, Base):
    __tablename__ = "player_guide_items"
    __table_args__ = (
        UniqueConstraint("server_id", "minecraft_nickname_normalized", "item_id", name="uq_player_guide_items_item"),
    )

    minecraft_nickname_normalized: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    minecraft_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
