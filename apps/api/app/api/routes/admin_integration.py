"""«Интеграция»: what an external server installs to join VoidRP, and whether it works.

For admins of partner servers (rights ``integration.view`` / ``integration.config``, per
server, part of server admin): the checklist from live plugin reports, our builds with their
versions and changes, ready configs with the server's secret (after the password), tips.
"""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import server_reports
from apps.api.app.core.audit import record_audit
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission, require_reauth
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.plugin_release import PluginRelease
from apps.api.app.models.user import User

router = APIRouter(prefix="/admin/integration", tags=["admin", "integration"],
                   dependencies=[Depends(require_permission("integration.view"))])

_Server = Annotated[GameServer, Depends(resolve_server)]
_Db = Annotated[Session, Depends(get_db_session)]


def _version_key(v: str | None) -> tuple:
    parts = []
    for p in (v or "").replace("-", ".").split("."):
        parts.append((0, int(p)) if p.isdigit() else (1, p))
    return tuple(parts)


def _release_view(r: PluginRelease) -> dict:
    return {
        "id": str(r.id), "version": r.version, "platforms": r.platforms, "mc_versions": r.mc_versions,
        "changelog": r.changelog, "filename": r.filename, "size": r.size, "sha256": r.sha256,
        "recommended": r.recommended, "published_at": r.published_at.isoformat() if r.published_at else None,
    }


@router.get("")
def overview(server: _Server, session: _Db) -> dict:
    reports = server_reports.reports(session, server)
    by_plugin = {r.plugin.lower(): r for r in reports}
    have = server_reports.modules(session, server)
    releases = session.scalars(select(PluginRelease).order_by(PluginRelease.published_at.desc())).all()

    items = []
    for e in cat.for_server(server):
        item = {k: v for k, v in e.items()}
        item["has_config"] = e["key"] in cat.CONFIG_BUILDERS
        if e["kind"] == "ours":
            own = [r for r in releases if r.plugin == e["key"]]
            own.sort(key=lambda r: _version_key(r.version), reverse=True)
            latest = next((r for r in own if r.recommended), own[0] if own else None)
            item["releases"] = [_release_view(r) for r in own]
            item["latest"] = _release_view(latest) if latest else None
            rep = by_plugin.get(e["name"].lower())
            installed = rep.version if rep else None
            item["installed"] = {
                "version": installed,
                "reported_at": rep.reported_at.isoformat() if rep else None,
                "fresh": server_reports.is_fresh(rep) if rep else False,
                "modules": rep.modules if rep else {},
            } if rep else None
            item["outdated"] = bool(installed and latest and _version_key(installed) < _version_key(latest.version))
        items.append(item)

    required = []
    for key, label in server_reports.REQUIRED_MODULES.items():
        state = have.get(key)
        required.append({"key": key, "label": label, "ok": state is not None,
                         "plugin": state and state["plugin"], "version": state and state["version"]})

    core_reported = next((r.core for r in reports if r.core and server_reports.is_fresh(r)), None)
    tips = []
    if server.is_external and server.rcon_port:
        tips.append({"level": "warn", "text": "RCON открыт в интернет, а пароль к нему идёт открытым текстом. "
                     "Когда модуль мониторинга работает, RCON админке не нужен: закройте порт "
                     f"{server.rcon_port} фаерволом или разрешите его только для 80.68.9.233."})
    if not server.server_core:
        tips.append({"level": "warn", "text": "Не указано ядро сервера (Paper, Folia, NeoForge…) — "
                     "владелец задаёт его в «Серверах». От него зависит, какой способ входа ставить."})
    return {
        "server": {"slug": server.slug, "name": server.name, "is_external": server.is_external,
                   "server_core": server.server_core, "core_label": cat.CORE_LABELS.get(server.server_core or ""),
                   "core_reported": core_reported, "auth_method": cat.auth_method(server),
                   "maintenance": server.maintenance, "is_visible": server.is_visible},
        "required": required,
        "missing_required": [r["label"] for r in required if not r["ok"]] if server.is_external else [],
        "items": items,
        "reports": [{"plugin": r.plugin, "version": r.version, "core": r.core, "modules": r.modules,
                     "reported_at": r.reported_at.isoformat(), "fresh": server_reports.is_fresh(r)} for r in reports],
        "tips": tips,
        "fresh_seconds": server_reports.FRESH_SECONDS,
    }


@router.get("/releases/{release_id}/download")
def download_release(release_id: UUID, session: _Db) -> FileResponse:
    r = session.get(PluginRelease, release_id)
    if r is None or not os.path.isfile(r.storage_path):
        raise HTTPException(status_code=404, detail="Файл релиза не найден")
    base = os.path.realpath(cat.releases_dir())
    if not os.path.realpath(r.storage_path).startswith(base + os.sep):
        raise HTTPException(status_code=404, detail="Файл релиза не найден")
    return FileResponse(r.storage_path, filename=r.filename, media_type="application/java-archive")


@router.get("/config/{key}", dependencies=[Depends(require_permission("integration.config")), Depends(require_reauth)])
def download_config(key: str, server: _Server, session: _Db, request: Request,
                    actor: Annotated[User, Depends(get_current_staff_user)]) -> PlainTextResponse:
    builder = cat.CONFIG_BUILDERS.get(key)
    e = cat.entry(key)
    if builder is None or e is None:
        raise HTTPException(status_code=404, detail="Для этого плагина нет конфига")
    # The file carries the server's secret: every download goes to the audit log.
    record_audit(session, category="integration", action="config_download", actor=actor,
                 target_type="server", target_id=str(server.id), target_label=server.slug,
                 server_id=server.id, meta={"plugin": key}, request=request)
    filename = os.path.basename(e["config_path"])
    return PlainTextResponse(builder(server), headers={"Content-Disposition": f'attachment; filename="{filename}"'})
