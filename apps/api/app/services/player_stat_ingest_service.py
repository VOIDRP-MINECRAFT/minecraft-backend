from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_stat_cache import PlayerStatCache
from apps.api.app.schemas.game_stats import PlayerStatDelta, PlayerStatsBatchRequest


class PlayerStatIngestService:
    """Applies incremental per-player stat deltas from a game mod into
    ``player_stat_cache`` (scoped to the calling server). Rows are created on first
    sight; counters accumulate. Suitable for servers without a nation layer (abyss)."""

    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def _user_id_by_nick(self, normalized: str) -> UUID | None:
        return self.session.scalar(
            select(PlayerAccount.user_id).where(
                PlayerAccount.minecraft_nickname_normalized == normalized
            )
        )

    def _apply_one(self, delta: PlayerStatDelta, now: datetime) -> None:
        nick = delta.nick.strip()
        if not nick:
            return
        normalized = nick.lower()

        row = self.session.scalar(
            select(PlayerStatCache).where(
                PlayerStatCache.server_id == self.server_id,
                PlayerStatCache.minecraft_nickname_normalized == normalized,
            )
        )
        if row is None:
            row = PlayerStatCache(
                server_id=self.server_id,
                minecraft_nickname=nick,
                minecraft_nickname_normalized=normalized,
                user_id=self._user_id_by_nick(normalized),
                source="live",
            )
            self.session.add(row)
        elif row.user_id is None:
            row.user_id = self._user_id_by_nick(normalized)

        # Counter columns can be None here: on a freshly-constructed row SQLAlchemy
        # applies the ``default=0`` only at INSERT/flush time, and legacy rows from
        # other code paths may hold NULL — so coalesce before accumulating.
        row.pvp_kills = (row.pvp_kills or 0) + delta.pvp_kills
        row.mob_kills = (row.mob_kills or 0) + delta.mob_kills
        row.deaths = (row.deaths or 0) + delta.deaths
        row.total_playtime_minutes = (row.total_playtime_minutes or 0) + delta.playtime_minutes
        row.blocks_placed = (row.blocks_placed or 0) + delta.blocks_placed
        row.blocks_broken = (row.blocks_broken or 0) + delta.blocks_broken
        row.source = "live"
        row.last_seen_at = now
        row.last_synced_at = now

    def apply_batch(self, req: PlayerStatsBatchRequest) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for delta in req.players:
            self._apply_one(delta, now)
            count += 1
        return count
