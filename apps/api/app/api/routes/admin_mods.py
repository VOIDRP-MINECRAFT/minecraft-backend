from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import manifest_ops, mod_ops
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User

router = APIRouter(
    prefix="/admin/mods",
    tags=["admin", "mods"],
    dependencies=[Depends(require_permission("mods.view"))],
)

_MANAGE = Depends(require_permission("mods.manage"))


def _fail(exc: mod_ops.ModOpsError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ── List ─────────────────────────────────────────────────────────────────────
@router.get("")
def list_mods(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    try:
        return mod_ops.list_mods(session, server)
    except mod_ops.ModOpsError as exc:
        raise _fail(exc)


# ── Upload → staging ─────────────────────────────────────────────────────────
@router.post("/upload", dependencies=[_MANAGE])
async def upload_mods(
    server: Annotated[GameServer, Depends(resolve_server)],
    files: list[UploadFile] = File(...),
) -> dict:
    payload: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        payload.append((f.filename or "", data))
    try:
        return mod_ops.stage_uploads(server.slug, payload)
    except mod_ops.ModOpsError as exc:
        raise _fail(exc)


# ── Apply staged uploads with per-file targets/flags ─────────────────────────
class ApplySelection(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    on_client: bool = False
    on_server: bool = False
    optional: bool = False
    required: bool = False
    display_name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class ApplyRequest(BaseModel):
    token: str = Field(min_length=1, max_length=64)
    selections: list[ApplySelection] = Field(min_length=1)


@router.post("/apply", dependencies=[_MANAGE])
def apply_mods(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
    payload: ApplyRequest,
) -> dict:
    external = getattr(server, "is_external", False)
    selections = []
    for s in payload.selections:
        d = s.model_dump()
        if external:
            d["on_server"] = False   # partner server: no server-side mods (not our machine)
        selections.append(d)
    try:
        result = mod_ops.apply_staged(
            session, server, payload.token, selections,
            updated_by=admin.site_login,
        )
        session.commit()
        return result
    except mod_ops.ModOpsError as exc:
        session.rollback()
        raise _fail(exc)


# ── Update metadata (optional/required/name/desc) for an existing mod ────────
class MetaRequest(BaseModel):
    optional: bool = False
    required: bool = False
    display_name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


@router.patch("/{filename}/meta", dependencies=[_MANAGE])
def update_meta(
    filename: str,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
    payload: MetaRequest,
) -> dict:
    try:
        base = mod_ops.sanitize_jar(filename)
        mod_ops.upsert_meta(
            session, server, base,
            optional=payload.optional, required=payload.required,
            display_name=payload.display_name, description=payload.description,
            updated_by=admin.site_login,
        )
        session.commit()
        return {"filename": base, "ok": True}
    except mod_ops.ModOpsError as exc:
        session.rollback()
        raise _fail(exc)


# ── Toggle client/server presence for an existing mod ────────────────────────
class TargetsRequest(BaseModel):
    on_client: bool
    on_server: bool


@router.patch("/{filename}/targets", dependencies=[_MANAGE])
def set_targets(
    filename: str,
    server: Annotated[GameServer, Depends(resolve_server)],
    payload: TargetsRequest,
) -> dict:
    # Partner (external) server: its mods folder is on someone else's machine — never place
    # a mod server-side there. Keep only the client-pack target.
    on_server = payload.on_server and not getattr(server, "is_external", False)
    try:
        return mod_ops.set_targets(server, filename, payload.on_client, on_server)
    except mod_ops.ModOpsError as exc:
        raise _fail(exc)


# ── Remove (soft — to trash) ─────────────────────────────────────────────────
@router.delete("/{filename}", dependencies=[_MANAGE])
def remove_mod(
    filename: str,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    target: Annotated[str, Query(pattern=r"^(client|server|both)$")] = "both",
) -> dict:
    try:
        result = mod_ops.remove_mod(session, server, filename, target)
        session.commit()
        return result
    except mod_ops.ModOpsError as exc:
        session.rollback()
        raise _fail(exc)


# ── Regenerate the launcher manifest for this server (async job) ─────────────
# Starts a detached rebuild and streams progress; the admin modal polls
# GET /regenerate/status for the live console + %-bar.
@router.post("/regenerate", dependencies=[_MANAGE])
def regenerate(
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    try:
        return manifest_ops.start(server)
    except mod_ops.ModOpsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/regenerate/status", dependencies=[_MANAGE])
def regenerate_status() -> dict:
    return manifest_ops.get_status()
