from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.player_activity import CLIENT_EXTERNAL, CLIENT_LAUNCHER, PlayerServerActivity
from apps.api.app.core.security import utc_now


class PlayerActivityService:
    """Records where a player plays and what they connect with.

    Called once per successful login: by the play-ticket flow (our launcher) and by the
    login plugin on the plugin servers (third-party clients). Cheap upsert — one indexed
    row per player per server.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, *, user_id: UUID, server_id: UUID, client: str) -> PlayerServerActivity:
        client = CLIENT_LAUNCHER if client == CLIENT_LAUNCHER else CLIENT_EXTERNAL
        now = utc_now()

        row = self.session.execute(
            select(PlayerServerActivity).where(
                PlayerServerActivity.user_id == user_id,
                PlayerServerActivity.server_id == server_id,
            )
        ).scalar_one_or_none()

        if row is None:
            row = PlayerServerActivity(
                user_id=user_id,
                server_id=server_id,
                first_seen_at=now,
                last_seen_at=now,
                last_client=client,
                launcher_logins=1 if client == CLIENT_LAUNCHER else 0,
                external_logins=0 if client == CLIENT_LAUNCHER else 1,
            )
            self.session.add(row)
            return row

        row.last_seen_at = now
        row.last_client = client
        if client == CLIENT_LAUNCHER:
            row.launcher_logins += 1
        else:
            row.external_logins += 1
        return row
