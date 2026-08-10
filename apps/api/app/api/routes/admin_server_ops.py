from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.api.app.config import get_settings
from apps.api.app.core import server_ops
from apps.api.app.dependencies.admin import caller_permissions, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer

router = APIRouter(
    prefix="/admin/server-ops",
    tags=["admin", "server-ops"],
    dependencies=[Depends(require_permission("monitoring.view"))],
)


# ── System / process / disk metrics ─────────────────────────────────────────
@router.get("/metrics")
def get_metrics(server: Annotated[GameServer, Depends(resolve_server)]) -> dict:
    """Host CPU/RAM/load/uptime, the server JVM's CPU/RAM, and disk usage of
    the drive the server's data lives on. Blocks ~0.35s for a CPU sample."""
    return server_ops.collect_metrics(server)


# ── RCON-derived live view (players + TPS) ──────────────────────────────────
@router.get("/live")
def get_live(
    server: Annotated[GameServer, Depends(resolve_server)],
    perms: Annotated[set[str], Depends(caller_permissions)],
) -> dict:
    # Players come from the status/query protocol (locale-proof, real names);
    # TPS needs RCON. The two are independent so one failing doesn't hide the other.
    players = server_ops.collect_players(server)
    rcon_configured = bool(server.rcon_port and server.rcon_password is not None)
    tps: dict | None = None
    rcon_error: str | None = None
    if rcon_configured:
        try:
            tps = server_ops.query_tps(server)
        except Exception as exc:
            rcon_error = str(exc)
    # The online-players list is its own permission — don't leak it to callers
    # who only hold monitoring.view.
    can_see_players = "players.online.view" in perms
    return {
        "online": players is not None,
        "rcon_configured": rcon_configured,
        "rcon_error": rcon_error,
        "players": players if can_see_players else None,
        "can_view_players": can_see_players,
        "tps": tps,
    }


# ── Player moderation (kick / ban / op) — its own permission ─────────────────
class ModerateRequest(BaseModel):
    action: str = Field(pattern=r"^(kick|ban|op)$")
    player: str = Field(min_length=1, max_length=32)


@router.post("/moderate", dependencies=[Depends(require_permission("players.online.moderate"))])
def moderate_player(
    server: Annotated[GameServer, Depends(resolve_server)],
    payload: ModerateRequest,
) -> dict:
    """Kick/ban/op an online player. Decoupled from the full RCON console so a
    moderator can hold players.online.moderate without arbitrary RCON access."""
    import re

    name = payload.player.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
        raise HTTPException(status_code=400, detail="Некорректный ник игрока")
    try:
        output = server_ops.rcon_command(server, f"{payload.action} {name}")
    except server_ops.RconNotConfigured:
        raise HTTPException(status_code=409, detail="RCON is not configured for this server")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"RCON error: {exc}")
    return {"action": payload.action, "player": name, "output": server_ops.strip_color_codes(output)}


# ── RCON console ────────────────────────────────────────────────────────────
class RconRequest(BaseModel):
    command: str = Field(min_length=1, max_length=512)


@router.post("/rcon", dependencies=[Depends(require_permission("monitoring.rcon"))])
def run_rcon(
    server: Annotated[GameServer, Depends(resolve_server)],
    payload: RconRequest,
) -> dict:
    try:
        output = server_ops.rcon_command(server, payload.command.strip())
    except server_ops.RconNotConfigured:
        raise HTTPException(status_code=409, detail="RCON is not configured for this server")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"RCON error: {exc}")
    return {"command": payload.command, "output": server_ops.strip_color_codes(output)}


# ── Log tail ────────────────────────────────────────────────────────────────
@router.get("/logs")
def get_logs(
    server: Annotated[GameServer, Depends(resolve_server)],
    source: Annotated[str, Query(pattern=r"^(server|watchdog)$")] = "server",
    lines: Annotated[int, Query(ge=1, le=1000)] = 250,
) -> dict:
    if source == "watchdog":
        path = get_settings().watchdog_log_path or None
    else:
        path = server_ops.resolve_log_path(server)
    if not path:
        return {"source": source, "path": None, "lines": [], "available": False}
    content = server_ops.tail_log(path, lines=lines)
    return {"source": source, "path": path, "lines": content, "available": True}
