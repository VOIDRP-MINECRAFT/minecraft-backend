"""Game server side of remote files (VoidRpPerms modules.files, core/remote_files.py).

The plugin takes its jobs from ``/files/pending``, posts each result to ``/files/{id}/result``
and downloads uploaded plugin jars from ``/files/blob/{id}`` — all with its own secret, and
only its own server's jobs and uploads.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import remote_files
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer

router = APIRouter(prefix="/game-sync/files", tags=["game-sync"])

_Server = Annotated[GameServer, Depends(require_game_server)]
_Db = Annotated[Session, Depends(get_db_session)]


@router.get("/pending")
def pending(server: _Server, session: _Db) -> dict:
    rows = remote_files.take_pending(session, server)
    return {"jobs": [{"id": r.id, "op": r.op, **(r.args or {})} for r in rows]}


class JobResult(BaseModel):
    ok: bool = True
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=4000)
    status: int | None = None


@router.post("/{job_id}/result")
def result(job_id: int, body: JobResult, server: _Server, session: _Db) -> dict:
    if not remote_files.finish(session, server, job_id, body.ok, body.result, body.error, body.status):
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return {"ok": True}


@router.get("/blob/{blob_id}")
def blob(blob_id: str, server: _Server):
    p = remote_files.blob_path(server, blob_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(p, media_type="application/octet-stream")
