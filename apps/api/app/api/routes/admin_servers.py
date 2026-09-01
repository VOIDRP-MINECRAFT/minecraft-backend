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
from apps.api.app.core import server_provision
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission
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
    dependencies=[Depends(require_permission("servers.manage"))],
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


def _next_free_rcon_port(session: Session) -> int:
    """A local RCON port not already used by another server (they share 127.0.0.1)."""
    used = {s.rcon_port for s in GameServerRepository(session).list_all() if s.rcon_port}
    port = max(used) + 1 if used else 25575
    while port in used:
        port += 1
    return port


@router.get("/suggest-paths")
def suggest_paths(
    session: Annotated[Session, Depends(get_db_session)],
    slug: Annotated[str, Query(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")],
    neoforge_version: Annotated[str | None, Query()] = None,
    mc_version: Annotated[str | None, Query()] = None,
    loader: Annotated[str | None, Query()] = None,
    java_version: Annotated[int | None, Query()] = None,
) -> dict:
    """Derived modpack + monitoring defaults for a new server (slug + core
    version). The create form calls this to prefill blank fields; everything
    stays editable. Runtime is reused from a same-engine server if one exists,
    else flagged as new-engine (runtime_needs_build)."""
    fields = server_provision.suggested_fields(slug, neoforge_version, mc_version)
    fields["rcon_port"] = _next_free_rcon_port(session)
    existing = GameServerRepository(session).list_all()
    fields.update(server_provision.resolve_runtime(
        existing, slug, mc_version, loader or "neoforge", java_version, neoforge_version
    ))
    return fields


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

    # Partner (external) server: our client pack + launcher + RCON, but the game host is on
    # someone else's machine — so it has no systemd service / data dir / log path on our side.
    if data.get("is_external") and data.get("is_default"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Внешний сервер не может быть сервером по умолчанию.")

    # Auto-provision: fill any blank modpack/monitoring path field from the
    # slug+version convention, then create the on-disk folder skeleton. Explicit
    # values the admin typed are kept as-is; only blanks are filled.
    suggestions = server_provision.suggested_fields(
        data["slug"], data.get("neoforge_version"), data.get("mc_version")
    )
    for field, default in suggestions.items():
        if default and not data.get(field):
            data[field] = default
    if not data.get("rcon_port"):
        data["rcon_port"] = _next_free_rcon_port(session)

    # Runtime: reuse a same-engine server's runtime, or (new engine) point at
    # per-server runtime files and scaffold the build script. Only fills blanks.
    rt = server_provision.resolve_runtime(
        repo.list_all(), data["slug"], data.get("mc_version"),
        data.get("loader"), data.get("java_version"), data.get("neoforge_version"),
    )
    for field in ("runtime_seed_url", "runtime_manifest_url", "manifest_build_script"):
        if rt.get(field) and not data.get(field):
            data[field] = rt[field]
    # New engine → generate the pack+runtime build script if that's the chosen one.
    if rt["runtime_needs_build"] and data.get("manifest_build_script") == server_provision.runtime_build_script_rel(data["slug"]):
        server_provision.write_runtime_build_script(
            data["slug"], name=data["name"], mc_version=data.get("mc_version"),
            loader=data.get("loader"), neoforge_version=data.get("neoforge_version"),
            java_version=data.get("java_version"), port=data.get("port"),
        )

    # Partner server: not our machine → no systemd unit / data dir / log path (our pack,
    # launcher and RCON stay as-is). Clear any convention-filled local-ops paths.
    if data.get("is_external"):
        data["systemd_unit"] = None
        data["data_dir"] = None
        data["log_path"] = None

    try:
        server_provision.provision_dirs(data.get("pack_root"), data.get("data_dir"))
    except server_provision.ServerProvisionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

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
