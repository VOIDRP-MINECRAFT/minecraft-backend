from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.kill_event import KillEvent
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.killfeed import (
    KillEventIngest,
    KillEventRead,
    KillfeedResponse,
)

_MAX_FEED = 50


class KillfeedService:
    """Append-only PvP kill log for the public anarchy killfeed (server-scoped)."""

    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def _user_id_by_nick(self, nick: str) -> UUID | None:
        return self.session.scalar(
            select(PlayerAccount.user_id).where(
                PlayerAccount.minecraft_nickname_normalized == nick.strip().lower()
            )
        )

    def record(self, ingest: KillEventIngest) -> None:
        weapon = ingest.weapon
        if weapon in ("", "minecraft:air"):
            weapon = None
        event = KillEvent(
            server_id=self.server_id,
            kind=ingest.kind or "pvp",
            killer_nick=ingest.killer_nick,
            killer_user_id=self._user_id_by_nick(ingest.killer_nick),
            victim_nick=ingest.victim_nick,
            victim_user_id=self._user_id_by_nick(ingest.victim_nick),
            weapon=weapon,
        )
        self.session.add(event)

    def recent(self, limit: int = _MAX_FEED) -> KillfeedResponse:
        limit = max(1, min(limit, _MAX_FEED))
        rows = self.session.scalars(
            select(KillEvent)
            .where(KillEvent.server_id == self.server_id)
            .order_by(KillEvent.created_at.desc())
            .limit(limit)
        ).all()
        return KillfeedResponse(
            events=[
                KillEventRead(
                    kind=r.kind,
                    killer_nick=r.killer_nick,
                    victim_nick=r.victim_nick,
                    weapon=r.weapon,
                    created_at=r.created_at,
                )
                for r in rows
            ]
        )
