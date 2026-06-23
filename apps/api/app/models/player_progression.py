from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

PROGRESSION_TIERS = [
    "create_age",
    "mekanism_age",
    "ae2_age",
    "quantum_age",   # quantum_circuit крафтится из AE2-компонентов — до реактора
    "reactor_age",   # reactor_heart требует quantum_circuit как ингредиент
    "draconic_age",
    "endgame",
]

TIER_LABELS: dict[str, str] = {
    "create_age": "Эпоха механизмов",
    "mekanism_age": "Эпоха стали",
    "ae2_age": "Эпоха автоматизации",
    "reactor_age": "Эпоха реакторов",
    "draconic_age": "Эпоха дракона",
    "quantum_age": "Квантовая эпоха",
    "endgame": "Эндгейм",
}


class PlayerProgression(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_progressions"
    __table_args__ = (
        UniqueConstraint(
            "minecraft_nickname_normalized",
            "tier_name",
            name="uq_player_progression_tier",
        ),
    )

    minecraft_nickname: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    minecraft_nickname_normalized: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    minecraft_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    tier_name: Mapped[str] = mapped_column(String(64), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
