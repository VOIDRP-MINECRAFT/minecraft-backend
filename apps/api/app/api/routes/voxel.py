"""Game-facing Voxel Engine channel (mod ↔ backend).

The in-game mod authenticates with its per-server ``X-Game-Auth-Secret`` and
pulls its game catalog here, then reports back load results — the two-way
channel of Этап 1. Everything is scoped to the authenticated server.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
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


class ZoneBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    dimension: str = "minecraft:overworld"
    min: list[int] = Field(min_length=3, max_length=3)
    max: list[int] = Field(min_length=3, max_length=3)


@router.post("/games/{game_id}/zone", status_code=status.HTTP_204_NO_CONTENT)
def upsert_zone(
    game_id: str,
    payload: ZoneBody,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> None:
    """Записать зону в definition игры из мира (мод, /engine zone set). Бампает version."""
    repo = VoxelGameRepository(session)
    game = repo.get(server.id, game_id)
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    definition: dict[str, Any] = dict(game.definition or {})
    zones = dict(definition.get("zones") or {})
    zones[payload.name] = {
        "type": "box",
        "dimension": payload.dimension,
        "min": payload.min,
        "max": payload.max,
    }
    definition["zones"] = zones
    game.definition = definition
    game.version += 1
    session.commit()
