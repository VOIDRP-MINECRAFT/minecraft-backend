from __future__ import annotations

import hmac
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.game_server import GameServer


class GameServerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, server_id: UUID) -> GameServer | None:
        return self.session.get(GameServer, server_id)

    def get_by_slug(self, slug: str) -> GameServer | None:
        statement = select(GameServer).where(GameServer.slug == slug)
        return self.session.execute(statement).scalar_one_or_none()

    def get_default(self) -> GameServer | None:
        statement = (
            select(GameServer)
            .where(GameServer.is_default.is_(True))
            .order_by(GameServer.sort_order.asc())
        )
        return self.session.execute(statement).scalars().first()

    def get_by_secret(self, secret: str) -> GameServer | None:
        """Constant-time match of an incoming X-Game-Auth-Secret against all servers."""
        if not secret:
            return None
        for server in self.list_all():
            if hmac.compare_digest(server.game_auth_secret, secret):
                return server
        return None

    def list_all(self) -> list[GameServer]:
        statement = select(GameServer).order_by(
            GameServer.sort_order.asc(), GameServer.name.asc()
        )
        return list(self.session.execute(statement).scalars().all())

    def list_visible(self) -> list[GameServer]:
        statement = (
            select(GameServer)
            .where(GameServer.is_visible.is_(True))
            .order_by(GameServer.sort_order.asc(), GameServer.name.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def add(self, server: GameServer) -> GameServer:
        self.session.add(server)
        self.session.flush()
        return server

    def delete(self, server: GameServer) -> None:
        self.session.delete(server)

    def clear_default_flag(self, except_id: UUID | None = None) -> None:
        """Ensure at most one default server."""
        for server in self.list_all():
            if server.is_default and server.id != except_id:
                server.is_default = False
