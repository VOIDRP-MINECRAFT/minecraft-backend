"""Game-facing Voxel Engine channel (mod ↔ backend).

The in-game mod authenticates with its per-server ``X-Game-Auth-Secret`` and
pulls its game catalog here, then reports back load results — the two-way
channel of Этап 1. Everything is scoped to the authenticated server.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.repositories.voxel_game_repository import VoxelGameRepository
from apps.api.app.schemas.voxel_game import VoxelGameStatusReport, VoxelGameSync

router = APIRouter(prefix="/voxel", tags=["voxel"])


@router.get("/games", response_model=list[VoxelGameSync])
def list_games(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> list:
    """Enabled game definitions for the calling server. The mod loads the one
    flagged ``is_active`` and uses ``version`` to detect changes for reload."""
    return VoxelGameRepository(session).list_for_server(server.id, only_enabled=True)


@router.post("/games/{game_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def report_status(
    game_id: str,
    payload: VoxelGameStatusReport,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> None:
    """Mod reports the result of loading a game (ok / error + message + which
    version). Surfaced in the admin panel so authoring isn't done blind."""
    repo = VoxelGameRepository(session)
    game = repo.get(server.id, game_id)
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    repo.record_status(game, payload.status, payload.version, payload.message)
    session.commit()
