from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_activity_log import NationActivityLog
from apps.api.app.models.user import User
from apps.api.app.schemas.nation_activity import (
    NationActivityActorRead,
    NationActivityLogListResponse,
    NationActivityLogRead,
)


class NationActivityNotFoundError(Exception): ...


class NationActivityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        nation_id,
        event_type: str,
        actor_user_id=None,
        target_user_id=None,
        message: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            NationActivityLog(
                nation_id=nation_id,
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                event_type=event_type,
                message=message,
                metadata_json=metadata or {},
            )
        )

    def list_for_slug(self, slug: str, limit: int = 30) -> NationActivityLogListResponse:
        nation = self.session.execute(select(Nation).where(Nation.slug == slug)).scalar_one_or_none()
        if nation is None:
            raise NationActivityNotFoundError("nation was not found")
        return self.list_for_nation_id(nation.id, limit=limit)

    def list_for_nation_id(self, nation_id, limit: int = 30) -> NationActivityLogListResponse:
        rows = (
            self.session.execute(
                select(NationActivityLog)
                .options(
                    joinedload(NationActivityLog.actor).joinedload(User.player_account),
                    joinedload(NationActivityLog.target).joinedload(User.player_account),
                )
                .where(NationActivityLog.nation_id == nation_id)
                .order_by(NationActivityLog.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return NationActivityLogListResponse(total=len(rows), items=[self._build_read(item) for item in rows])

    def _build_actor(self, user: User | None) -> NationActivityActorRead | None:
        if user is None:
            return None
        return NationActivityActorRead(
            user_id=user.id,
            site_login=user.site_login,
            minecraft_nickname=user.player_account.minecraft_nickname if user.player_account else None,
        )

    def _build_read(self, item: NationActivityLog) -> NationActivityLogRead:
        return NationActivityLogRead(
            id=item.id,
            nation_id=item.nation_id,
            event_type=item.event_type,
            message=item.message,
            metadata=item.metadata_json or {},
            actor=self._build_actor(item.actor),
            target=self._build_actor(item.target),
            created_at=item.created_at,
        )
