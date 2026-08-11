"""Admin "Лаунчер" tab — release status, version bump, build & deploy.

See core/launcher_ops.py for the mechanics. The deploy is a detached, long-
running job; the UI polls GET /status (or the lighter /log) for live progress.
"""
from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import launcher_ops
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import (
    get_current_staff_user,
    require_permission,
)
from apps.api.app.models.launcher_crash_report import LauncherCrashReport
from apps.api.app.models.user import User

router = APIRouter(prefix="/admin/launcher", tags=["admin", "launcher"])


class VersionUpdateRequest(BaseModel):
    version: str | None = None
    bump: str | None = None  # "patch"


class NotesUpdateRequest(BaseModel):
    notes: str = ""


def _public_manifest_ok() -> bool:
    url = get_settings().launcher_public_manifest_url
    try:
        resp = httpx.get(url, timeout=4.0)
        return resp.status_code == 200 and "version" in resp.text
    except httpx.HTTPError:
        return False


@router.get("/status", dependencies=[Depends(require_permission("launcher.view"))])
def get_status() -> dict:
    payload = launcher_ops.build_status_payload(include_log=True)
    payload["publicManifestOk"] = _public_manifest_ok()
    return payload


@router.get("/log", dependencies=[Depends(require_permission("launcher.view"))])
def get_log() -> dict:
    """Lightweight endpoint for fast polling during a build."""
    job = launcher_ops.get_job()
    text = launcher_ops.tail_log()
    stage, percent = launcher_ops.current_stage(text)
    if job.get("state") == "success":
        percent = 100
    return {
        "text": text,
        "stage": stage,
        "percent": percent,
        "running": bool(job.get("running")),
        "state": job.get("state"),
        "error": job.get("error"),
    }


@router.post("/version", dependencies=[Depends(require_permission("launcher.deploy"))])
def update_version(body: VersionUpdateRequest) -> dict:
    try:
        current = launcher_ops.read_current_version() or "0.0.0"
        target = body.version
        if body.bump == "patch" and not target:
            target = launcher_ops.bump_patch(launcher_ops.validate_semver(current))
        if not target:
            raise launcher_ops.LauncherOpsError("Не указана версия")
        launcher_ops.set_version(target)
    except launcher_ops.LauncherOpsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return launcher_ops.build_status_payload(include_log=False)


@router.post("/deploy", dependencies=[Depends(require_permission("launcher.deploy"))])
def start_deploy(actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    label = getattr(actor, "site_login", None) or getattr(actor, "email", None) or "admin"
    try:
        launcher_ops.start_deploy(label)
    except launcher_ops.LauncherOpsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return launcher_ops.build_status_payload(include_log=True)


@router.post("/cancel", dependencies=[Depends(require_permission("launcher.deploy"))])
def cancel_deploy() -> dict:
    launcher_ops.stop_deploy()
    return launcher_ops.build_status_payload(include_log=True)


@router.post("/notes", dependencies=[Depends(require_permission("launcher.deploy"))])
def update_notes(body: NotesUpdateRequest) -> dict:
    """Release notes applied to the manifest on the next deploy (shown to players
    in the update prompt)."""
    try:
        launcher_ops.set_notes(body.notes)
    except launcher_ops.LauncherOpsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"notes": launcher_ops.read_notes()}


@router.get("/history", dependencies=[Depends(require_permission("launcher.view"))])
def get_history() -> dict:
    return {"items": launcher_ops.read_history(limit=30)}


@router.post("/rollback", dependencies=[Depends(require_permission("launcher.deploy"))])
def rollback() -> dict:
    try:
        launcher_ops.rollback()
    except launcher_ops.LauncherOpsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return launcher_ops.build_status_payload(include_log=False)


@router.get("/crash-stats", dependencies=[Depends(require_permission("launcher.view"))])
def crash_stats(session: Annotated[Session, Depends(get_db_session)]) -> dict:
    """Crash counts + rough adoption by launcher_version, for the last 30 days.
    Ties the release page to [[project_launcher_crash_enrichment]]."""
    from datetime import datetime, timedelta, timezone

    # Group crashes by launcher_version (last 30 days) — count + distinct players.
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = session.execute(
        select(
            LauncherCrashReport.launcher_version,
            func.count().label("crashes"),
            func.count(func.distinct(LauncherCrashReport.player_nickname)).label("players"),
            func.max(LauncherCrashReport.created_at).label("last"),
        )
        .where(LauncherCrashReport.created_at >= cutoff)
        .group_by(LauncherCrashReport.launcher_version)
    ).all()
    versions = [
        {
            "version": r.launcher_version or "—",
            "crashes": int(r.crashes),
            "players": int(r.players),
            "last": r.last.isoformat() if r.last else None,
        }
        for r in rows
    ]
    versions.sort(key=lambda v: v["crashes"], reverse=True)
    total = sum(v["crashes"] for v in versions)
    return {"windowDays": 30, "total": total, "versions": versions}
