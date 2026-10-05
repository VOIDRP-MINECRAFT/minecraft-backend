"""The shell side of «Интеграция»: install.sh by a one-time token, update and doctor scripts.

* ``/i/{token}`` — ``install.sh`` for one server (the token comes from the panel, after the
  password, and lives 15 minutes); ``/i/{token}/bundle|file|config`` — what it downloads.
* ``/integration/voidrp-update.sh``, ``/integration/voidrp-doctor.sh`` — the same for every
  server: they hold no secret and take the server's own from its plugin config.
* ``/game-sync/integration/*`` — the list, the files and the doctor's report for a server
  that authenticates with its secret (the update script, ``doctor --send``).
"""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import integration_scripts as scripts
from apps.api.app.core.audit import record_audit
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.plugin_release import PluginRelease
from apps.api.app.models.user import User
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(tags=["integration-scripts"])

_Db = Annotated[Session, Depends(get_db_session)]
TOKEN_TTL = timedelta(minutes=15)
DOCTOR_TTL_SECONDS = 14 * 24 * 3600
DOCTOR_MAX_BYTES = 32 * 1024
_SHELL = "text/x-shellscript; charset=utf-8"


def _api() -> str:
    return get_settings().public_api_url.rstrip("/") + "/api/v1"


# ── One-time install tokens ───────────────────────────────────────────────────
def issue_token(server: GameServer, actor: User) -> dict:
    token = secrets.token_urlsafe(18)
    RedisCacheService().set_json(f"integration_install:{token}",
                                 {"server_id": str(server.id), "user_id": str(actor.id)},
                                 ttl_seconds=int(TOKEN_TTL.total_seconds()))
    return {"token": token, "expires_at": (utc_now() + TOKEN_TTL).isoformat(),
            "command": f"curl -fsSL {_api()}/i/{token} | bash",
            "command_all": f"curl -fsSL {_api()}/i/{token} | bash -s -- --all"}


def _by_token(token: str, session: Session) -> tuple[GameServer, dict]:
    data = RedisCacheService().get_json(f"integration_install:{token}") if len(token) < 64 else None
    server = session.get(GameServer, UUID(data["server_id"])) if data else None
    if server is None:
        raise HTTPException(status_code=404, detail="Ссылка устарела — возьмите новую в «Интеграции»")
    return server, data


def _release_file(release_id: UUID, session: Session) -> FileResponse:
    r = session.get(PluginRelease, release_id)
    base = os.path.realpath(cat.releases_dir())
    if (r is None or r.yanked or not os.path.isfile(r.storage_path)
            or not os.path.realpath(r.storage_path).startswith(base + os.sep)):
        raise HTTPException(status_code=404, detail="Файл релиза не найден")
    return FileResponse(r.storage_path, filename=r.filename, media_type="application/java-archive")


@router.get("/i/{token}", response_class=PlainTextResponse)
def install_script(token: str, session: _Db) -> PlainTextResponse:
    server, _ = _by_token(token, session)
    return PlainTextResponse(scripts.render(scripts.INSTALL, token=token, name=server.name, slug=server.slug),
                             media_type=_SHELL)


@router.get("/i/{token}/bundle", response_class=PlainTextResponse)
def install_bundle(token: str, session: _Db, all: int = 0) -> PlainTextResponse:
    server, _ = _by_token(token, session)
    text = scripts.bundle(session, server,
                          file_url=lambda rid: f"{_api()}/i/{token}/file/{rid}",
                          config_url=lambda key: f"{_api()}/i/{token}/config/{key}",
                          include_optional=bool(all))
    return PlainTextResponse(text)


@router.get("/i/{token}/file/{release_id}")
def install_file(token: str, release_id: UUID, session: _Db) -> FileResponse:
    _by_token(token, session)
    return _release_file(release_id, session)


@router.get("/i/{token}/config/{key}", response_class=PlainTextResponse)
def install_config(token: str, key: str, session: _Db, request: Request) -> PlainTextResponse:
    server, data = _by_token(token, session)
    builder = cat.CONFIG_BUILDERS.get(key)
    if builder is None:
        raise HTTPException(status_code=404, detail="Для этого плагина нет конфига")
    # The file carries the server's secret: logged under the person who issued the link.
    actor = session.get(User, UUID(data["user_id"]))
    record_audit(session, category="integration", action="config_download", actor=actor,
                 target_type="server", target_id=str(server.id), target_label=server.slug,
                 server_id=server.id, meta={"plugin": key, "via": "install.sh"}, request=request)
    return PlainTextResponse(builder(server))


# ── Scripts for every server ──────────────────────────────────────────────────
@router.get("/integration/voidrp-update.sh", response_class=PlainTextResponse)
def update_script() -> PlainTextResponse:
    return PlainTextResponse(scripts.render(scripts.UPDATE), media_type=_SHELL)


@router.get("/integration/voidrp-doctor.sh", response_class=PlainTextResponse)
def doctor_script() -> PlainTextResponse:
    return PlainTextResponse(scripts.render(scripts.DOCTOR), media_type=_SHELL)


# ── By the server's secret ────────────────────────────────────────────────────
_Server = Annotated[GameServer, Depends(require_game_server)]


@router.get("/game-sync/integration/bundle", response_class=PlainTextResponse)
def secret_bundle(server: _Server, session: _Db) -> PlainTextResponse:
    """For voidrp-update.sh: newer builds of what the server runs (no configs)."""
    return PlainTextResponse(scripts.bundle(session, server,
                                            file_url=lambda rid: f"{_api()}/game-sync/integration/file/{rid}",
                                            config_url=None, include_optional=False))


@router.get("/game-sync/integration/file/{release_id}")
def secret_file(release_id: UUID, server: _Server, session: _Db) -> FileResponse:
    return _release_file(release_id, session)


@router.post("/game-sync/integration/doctor", status_code=204)
async def doctor_report(server: _Server, request: Request) -> None:
    body = (await request.body())[:DOCTOR_MAX_BYTES].decode("utf-8", errors="replace")
    RedisCacheService().set_json(f"integration_doctor:{server.id}",
                                 {"text": body, "at": utc_now().isoformat()}, ttl_seconds=DOCTOR_TTL_SECONDS)


def doctor_of(server: GameServer) -> dict | None:
    return RedisCacheService().get_json(f"integration_doctor:{server.id}")
