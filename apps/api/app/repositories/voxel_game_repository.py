from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.voxel_game import VoxelGame


class VoxelGameRepository:
    """Data access for Voxel Engine game definitions. Every read is scoped by
    ``server_id`` so games never leak across servers."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_server(self, server_id: UUID, only_enabled: bool = False) -> list[VoxelGame]:
        stmt = select(VoxelGame).where(VoxelGame.server_id == server_id)
        if only_enabled:
            stmt = stmt.where(VoxelGame.enabled.is_(True))
        stmt = stmt.order_by(VoxelGame.game_id.asc())
        return list(self.session.execute(stmt).scalars().all())

    def get(self, server_id: UUID, game_id: str) -> VoxelGame | None:
        stmt = select(VoxelGame).where(
            VoxelGame.server_id == server_id, VoxelGame.game_id == game_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, server_id: UUID, row_id: UUID) -> VoxelGame | None:
        game = self.session.get(VoxelGame, row_id)
        if game is None or game.server_id != server_id:
            return None
        return game

    def get_active(self, server_id: UUID) -> VoxelGame | None:
        stmt = select(VoxelGame).where(
            VoxelGame.server_id == server_id, VoxelGame.is_active.is_(True)
        )
        return self.session.execute(stmt).scalars().first()

    def add(self, game: VoxelGame) -> VoxelGame:
        self.session.add(game)
        self.session.flush()
        return game

    def delete(self, game: VoxelGame) -> None:
        self.session.delete(game)

    def clear_active(self, server_id: UUID, except_id: UUID | None = None) -> None:
        """Ensure at most one active game per server."""
        for game in self.list_for_server(server_id):
            if game.is_active and game.id != except_id:
                game.is_active = False

    def record_status(
        self, game: VoxelGame, status: str, version: int, message: str | None
    ) -> None:
        game.last_report_status = status
        game.last_report_message = message
        game.last_reported_version = version
        game.last_reported_at = datetime.now(timezone.utc)
