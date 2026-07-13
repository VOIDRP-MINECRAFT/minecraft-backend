from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.api.app.models.player_stat_cache import PlayerStatCache
from apps.api.app.schemas.player_stats import PlayerTopCategory, PlayerTopEntry, PlayerTopResponse

TOP_LIMIT = 20

_CATEGORIES = [
    ("balance", "Богатейшие игроки", "монет", "current_balance"),
    ("pvp_kills", "Лучшие бойцы (PvP)", "убийств", "pvp_kills"),
    ("mob_kills", "Охотники на мобов", "убийств", "mob_kills"),
    ("playtime", "Старожилы", "часов", "total_playtime_minutes"),
    ("blocks_broken", "Шахтёры", "блоков", "blocks_broken"),
    ("blocks_placed", "Строители", "блоков", "blocks_placed"),
    ("completed_quests", "Искатели приключений", "заданий", "completed_quests"),
    ("deaths", "Чаще всего умирали", "смертей", "deaths"),
]


class PlayerStatsService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def get_top(self) -> PlayerTopResponse:
        categories: list[PlayerTopCategory] = []

        for key, label, unit, field_name in _CATEGORIES:
            column = getattr(PlayerStatCache, field_name)
            ascending = False

            order = column.asc() if ascending else desc(column)
            rows = (
                self.session.execute(
                    select(PlayerStatCache)
                    .where(PlayerStatCache.server_id == self.server_id)
                    .order_by(order)
                    .limit(TOP_LIMIT)
                )
                .scalars()
                .all()
            )

            entries: list[PlayerTopEntry] = []
            for i, row in enumerate(rows):
                raw = getattr(row, field_name)
                if field_name == "total_playtime_minutes":
                    value = round(raw / 60, 1)
                else:
                    value = float(raw)

                entries.append(
                    PlayerTopEntry(
                        rank=i + 1,
                        minecraft_nickname=row.minecraft_nickname,
                        value=value,
                        last_seen_at=row.last_seen_at,
                    )
                )

            categories.append(PlayerTopCategory(key=key, label=label, unit=unit, entries=entries))

        return PlayerTopResponse(categories=categories)
