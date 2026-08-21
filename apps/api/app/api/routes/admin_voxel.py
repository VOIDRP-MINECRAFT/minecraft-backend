"""Admin CRUD for Voxel Engine game definitions (backs the future webgui editor).

Server-scoped via ``resolve_server`` (``?server=`` / ``X-Server-Slug`` / default).
Editing a definition bumps ``version`` so the mod hot-reloads on next sync.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.voxel_game import VoxelGame
from apps.api.app.repositories.voxel_game_repository import VoxelGameRepository
from apps.api.app.schemas.voxel_game import (
    VoxelGameAdmin,
    VoxelGameCreate,
    VoxelGameUpdate,
)

router = APIRouter(
    prefix="/admin/voxel/games",
    tags=["admin", "voxel"],
    dependencies=[Depends(require_permission("voxel.view"))],
)


def _get_or_404(repo: VoxelGameRepository, server_id: UUID, row_id: UUID) -> VoxelGame:
    game = repo.get_by_id(server_id, row_id)
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return game


@router.get("", response_model=list[VoxelGameAdmin])
def list_games(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list:
    return VoxelGameRepository(session).list_for_server(server.id)


@router.post(
    "",
    response_model=VoxelGameAdmin,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("voxel.manage"))],
)
def create_game(
    payload: VoxelGameCreate,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> VoxelGame:
    repo = VoxelGameRepository(session)
    if repo.get(server.id, payload.game_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="game_id already exists on this server",
        )
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


@router.get("/{row_id}", response_model=VoxelGameAdmin)
def get_game(
    row_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> VoxelGame:
    return _get_or_404(VoxelGameRepository(session), server.id, row_id)


@router.patch(
    "/{row_id}",
    response_model=VoxelGameAdmin,
    dependencies=[Depends(require_permission("voxel.manage"))],
)
def update_game(
    row_id: UUID,
    payload: VoxelGameUpdate,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> VoxelGame:
    repo = VoxelGameRepository(session)
    game = _get_or_404(repo, server.id, row_id)

    updates = payload.model_dump(exclude_unset=True)
    if "definition" in updates and updates["definition"] is not None:
        game.definition = updates["definition"]
        game.version += 1  # мод сравнит version и перезагрузит
    if "name" in updates and updates["name"] is not None:
        game.name = updates["name"]
    if "enabled" in updates and updates["enabled"] is not None:
        game.enabled = updates["enabled"]
    if updates.get("is_active") is True:
        repo.clear_active(server.id, except_id=game.id)
        game.is_active = True
    elif updates.get("is_active") is False:
        game.is_active = False

    session.commit()
    session.refresh(game)
    return game


@router.delete(
    "/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("voxel.manage"))],
)
def delete_game(
    row_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> None:
    repo = VoxelGameRepository(session)
    game = _get_or_404(repo, server.id, row_id)
    repo.delete(game)
    session.commit()


@router.post(
    "/{row_id}/activate",
    response_model=VoxelGameAdmin,
    dependencies=[Depends(require_permission("voxel.manage"))],
)
def activate_game(
    row_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> VoxelGame:
    """Make this the single active game for the server (dispatcher runs it)."""
    repo = VoxelGameRepository(session)
    game = _get_or_404(repo, server.id, row_id)
    repo.clear_active(server.id, except_id=game.id)
    game.is_active = True
    game.enabled = True
    session.commit()
    session.refresh(game)
    return game
