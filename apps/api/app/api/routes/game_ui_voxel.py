"""In-game Voxel Engine editor — accessed from the WebGUI browser overlay.

The page opened by ``/engine editor`` runs inside the game and authenticates with
the per-player ``?webgui_token=`` (verified via :func:`get_webgui_player`). The
target server comes from ``?server=<slug>`` (``resolve_server``). Same data as the
site admin editor, but token-scoped to the player instead of an admin JWT.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.voxel_game import VoxelGame
from apps.api.app.repositories.voxel_game_repository import VoxelGameRepository
from apps.api.app.schemas.voxel_game import (
    VoxelGameAdmin,
    VoxelGameCreate,
    VoxelGameUpdate,
)

router = APIRouter(prefix="/game-ui/voxel", tags=["game-ui", "voxel"])


class ZoneUpsert(BaseModel):
    """Записать/обновить зону из игры (выбор области взглядом)."""
    game_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    dimension: str = "minecraft:overworld"
    min: list[int] = Field(min_length=3, max_length=3)
    max: list[int] = Field(min_length=3, max_length=3)


def _get_or_404(repo: VoxelGameRepository, server_id, game_id: str) -> VoxelGame:
    game = repo.get(server_id, game_id)
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return game


@router.get("/games", response_model=list[VoxelGameAdmin])
def list_games(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list:
    return VoxelGameRepository(session).list_for_server(server.id)


@router.post("/games", response_model=VoxelGameAdmin, status_code=status.HTTP_201_CREATED)
def create_game(
    payload: VoxelGameCreate,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> VoxelGame:
    repo = VoxelGameRepository(session)
    if repo.get(server.id, payload.game_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="game_id already exists")
    game = VoxelGame(
        server_id=server.id,
        game_id=payload.game_id,
        name=payload.name,
        definition=payload.definition,
        enabled=payload.enabled,
        is_active=payload.is_active,
        version=1,
    )
    if payload.is_active:
        repo.clear_active(server.id)
    repo.add(game)
    session.commit()
    session.refresh(game)
    return game


@router.patch("/games/{game_id}", response_model=VoxelGameAdmin)
def update_game(
    game_id: str,
    payload: VoxelGameUpdate,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> VoxelGame:
    repo = VoxelGameRepository(session)
    game = _get_or_404(repo, server.id, game_id)

    updates = payload.model_dump(exclude_unset=True)
    if updates.get("definition") is not None:
        game.definition = updates["definition"]
        game.version += 1
    if updates.get("name") is not None:
        game.name = updates["name"]
    if updates.get("enabled") is not None:
        game.enabled = updates["enabled"]
    if updates.get("is_active") is True:
        repo.clear_active(server.id, except_id=game.id)
        game.is_active = True
    elif updates.get("is_active") is False:
        game.is_active = False

    session.commit()
    session.refresh(game)
    return game


@router.post("/games/{game_id}/activate", response_model=VoxelGameAdmin)
def activate_game(
    game_id: str,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> VoxelGame:
    repo = VoxelGameRepository(session)
    game = _get_or_404(repo, server.id, game_id)
    repo.clear_active(server.id, except_id=game.id)
    game.is_active = True
    game.enabled = True
    session.commit()
    session.refresh(game)
    return game


@router.post("/zone", response_model=VoxelGameAdmin)
def upsert_zone(
    payload: ZoneUpsert,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> VoxelGame:
    """Записать зону в definition игры (из выбора области в мире). Бампает version."""
    repo = VoxelGameRepository(session)
    game = _get_or_404(repo, server.id, payload.game_id)

    definition: dict[str, Any] = dict(game.definition or {})
    zones = dict(definition.get("zones") or {})
    zones[payload.name] = {
        "type": "box",
        "dimension": payload.dimension,
        "min": payload.min,
        "max": payload.max,
    }
    definition["zones"] = zones
    game.definition = definition  # reassign → SQLAlchemy видит изменение JSONB
    game.version += 1

    session.commit()
    session.refresh(game)
    return game
