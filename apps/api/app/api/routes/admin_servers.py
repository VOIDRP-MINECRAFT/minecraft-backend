from __future__ import annotations

import secrets
from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.models.game_server import GameServer
from apps.api.app.repositories.game_server_repository import GameServerRepository
from apps.api.app.schemas.game_server import (
    GameServerAdmin,
    GameServerCreate,
    GameServerUpdate,
)

router = APIRouter(
    prefix="/admin/servers",
    tags=["admin", "servers"],
    dependencies=[Depends(require_admin_access)],
)

_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
_MAX_BYTES = 8 * 1024 * 1024
_MAX_WIDTH = {"icon": 256, "banner": 1600}


def _get_or_404(repo: GameServerRepository, server_id: UUID) -> GameServer:
    server = repo.get_by_id(server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return server


@router.get("", response_model=list[GameServerAdmin])
def list_servers(session: Annotated[Session, Depends(get_db_session)]) -> list[GameServer]:
    return GameServerRepository(session).list_all()


@router.post("", response_model=GameServerAdmin, status_code=status.HTTP_201_CREATED)
def create_server(
    payload: GameServerCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> GameServer:
    repo = GameServerRepository(session)
    if repo.get_by_slug(payload.slug) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")

    data = payload.model_dump()
    secret = data.pop("game_auth_secret", None) or secrets.token_urlsafe(32)
    # Let the column default (all features on) apply when not explicitly provided.
    if data.get("features") is None:
        data.pop("features", None)

    server = GameServer(**data, game_auth_secret=secret)
    if server.is_default:
        repo.clear_default_flag()
    repo.add(server)
    # Guarantee at least one default exists.
    if repo.get_default() is None:
        server.is_default = True
    session.commit()
    session.refresh(server)
    return server


@router.get("/{server_id}", response_model=GameServerAdmin)
def get_server(
    server_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> GameServer:
    return _get_or_404(GameServerRepository(session), server_id)


@router.patch("/{server_id}", response_model=GameServerAdmin)
def update_server(
    server_id: UUID,
    payload: GameServerUpdate,
    session: Annotated[Session, Depends(get_db_session)],
) -> GameServer:
    repo = GameServerRepository(session)
    server = _get_or_404(repo, server_id)

    updates = payload.model_dump(exclude_unset=True)
    if updates.get("is_default") is True:
        repo.clear_default_flag(except_id=server.id)
    # Never null out the NOT NULL features column.
    if "features" in updates and updates["features"] is None:
        updates.pop("features")
    for field, value in updates.items():
        setattr(server, field, value)

    session.commit()
    session.refresh(server)
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    repo = GameServerRepository(session)
    server = _get_or_404(repo, server_id)
    if server.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete the default server; set another server as default first",
        )
    repo.delete(server)
    session.commit()


@router.post("/{server_id}/regenerate-secret", response_model=GameServerAdmin)
def regenerate_secret(
    server_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> GameServer:
    repo = GameServerRepository(session)
    server = _get_or_404(repo, server_id)
    server.game_auth_secret = secrets.token_urlsafe(32)
    session.commit()
    session.refresh(server)
    return server


@router.post("/{server_id}/image", response_model=GameServerAdmin)
async def upload_image(
    server_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    kind: Annotated[str, Query(pattern=r"^(icon|banner)$")] = "icon",
    file: UploadFile = File(...),
) -> GameServer:
    repo = GameServerRepository(session)
    server = _get_or_404(repo, server_id)

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="file too large (max 8 MB)")

    try:
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if (img.format or "").upper() not in _ALLOWED_FORMATS:
                raise HTTPException(status_code=400, detail="only png, jpeg, webp allowed")
            working = img.convert("RGBA" if kind == "icon" else "RGB")
            max_w = _MAX_WIDTH[kind]
            if working.width > max_w:
                ratio = max_w / working.width
                working = working.resize(
                    (int(working.width * ratio), int(working.height * ratio)),
                    Image.Resampling.LANCZOS,
                )
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="not a valid image")

    settings = get_settings()
    rel_dir = Path("servers") / str(server.id)
    filename = f"{kind}-{uuid4().hex}.webp"
    storage_key = (rel_dir / filename).as_posix()

    abs_dir = Path(settings.media_storage_root) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    working.save(abs_dir / filename, format="WEBP", quality=90, method=4)

    url = f"{settings.media_public_base_url}/{storage_key}"
    if kind == "icon":
        server.icon_url = url
    else:
        server.banner_url = url

    session.commit()
    session.refresh(server)
    return server
