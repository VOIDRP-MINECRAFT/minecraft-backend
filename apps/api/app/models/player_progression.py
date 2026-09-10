from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import (
    Base,
    ServerScopedMixin,
    TimestampMixin,
    UuidPrimaryKeyMixin,
)

# Эпохи прогрессии. Список ОБЯЗАН совпадать с секцией `epochs.list` в
# config.yml плагина voidrp_gamesync_plugin: сервис отвергает незнакомый tier
# (UnknownTierError), поэтому переименование эпохи только в плагине приводит к
# тихой потере всех анлоков — в логе плагина будет «Бэкенд не принял <ключ>».
#
# Порядок = порядок общей линии; ветки идут после неё и на «текущую эпоху»
# игрока не влияют, потому что не обязательны и не upgrade-ят друг друга.
MAIN_PROGRESSION_TIERS = [
    "mechanisms_age",
    "steel_age",
    "energy_age",
    "automation_age",
    "industry_age",
    "quantum_age",
    "singularity_age",
    "transcendence",
]

BRANCH_PROGRESSION_TIERS = [
    "magic_path",
    "arcane_path",
    "hunter_path",
    "starlight_path",
    "draconic_path",
]

# Эпохи до 2026-09-08 удалены вместе с их записями: строк с ними в
# player_progressions не осталось (проверено), а держать мёртвые ключи в списке
# значит показывать их на странице рейтинга.
PROGRESSION_TIERS = MAIN_PROGRESSION_TIERS + BRANCH_PROGRESSION_TIERS

TIER_BRANCHES: dict[str, str] = {
    **{t: "main" for t in MAIN_PROGRESSION_TIERS},
    "magic_path": "magic",
    "arcane_path": "magic",
    "hunter_path": "exploration",
    "starlight_path": "exploration",
    "draconic_path": "tech",
}

TIER_LABELS: dict[str, str] = {
    # Общая линия
    "mechanisms_age": "Эпоха механизмов",
    "steel_age": "Эпоха стали",
    "energy_age": "Эпоха энергии",
    "automation_age": "Эпоха автоматизации",
    "industry_age": "Индустриальная эпоха",
    "quantum_age": "Квантовая эпоха",
    "singularity_age": "Эпоха сингулярности",
    "transcendence": "Трансцендентство",
    # Ветки
    "magic_path": "Путь магии",
    "arcane_path": "Тайные искусства",
    "hunter_path": "Путь охотника",
    "starlight_path": "Вечный Звездосвет",
    # Draconic Evolution — про дракониум и Стража Хаоса, драконов как таковых
    # в паке нет (Ice and Fire не установлен), поэтому название без «драконов».
    "draconic_path": "Дракониевая энергетика",
}


class PlayerProgression(UuidPrimaryKeyMixin, ServerScopedMixin, TimestampMixin, Base):
    __tablename__ = "player_progressions"
    __table_args__ = (
        UniqueConstraint(
            "server_id",
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
