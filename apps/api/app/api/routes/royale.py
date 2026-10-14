"""Royale (battle royale) results: the VoidRpRoyale plugin posts every finished game here,
and the admin panel lists them, shows each in full and exports them as a table for the
Academy's teaching staff (CSV that opens in Excel).

The plugin also posts the live state every couple of seconds; it lives in Redis for a short
while and the public /royale/live feeds the projector page on the site.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.royale import RoyaleMatch
from apps.api.app.models.user import User
from apps.api.app.services.redis_cache_service import RedisCacheService

MOSCOW = ZoneInfo("Europe/Moscow")

plugin_router = APIRouter(prefix="/game-sync/royale", tags=["game-sync", "royale"])
public_router = APIRouter(prefix="/royale", tags=["royale"])
admin_router = APIRouter(
    prefix="/admin/royale",
    tags=["admin", "royale"],
    dependencies=[Depends(require_permission("royale.view"))],
)


def _when(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── The plugin ────────────────────────────────────────────────────────────────

@plugin_router.post("/matches")
def receive_match(
    payload: dict[str, Any],
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    match_uuid = str(payload.get("match_id") or "")[:36]
    if len(match_uuid) < 8:
        raise HTTPException(status_code=400, detail="match_id is required")
    row = session.query(RoyaleMatch).filter(RoyaleMatch.match_uuid == match_uuid).one_or_none()
    if row is None:
        row = RoyaleMatch(match_uuid=match_uuid, server_id=server.id, server_slug=server.slug, map="", payload={})
        session.add(row)
    row.map = str(payload.get("map") or "")[:64]
    row.map_title = (str(payload.get("map_title")) if payload.get("map_title") else None)
    row.started_at = _when(payload.get("started_at"))
    row.ended_at = _when(payload.get("ended_at"))
    row.duration_seconds = int(payload.get("duration_seconds") or 0)
    row.aborted = bool(payload.get("aborted"))
    row.winner = payload.get("winner")
    row.winner_title = payload.get("winner_title")
    row.teams_count = len(payload.get("teams") or [])
    row.players_count = len(payload.get("players") or [])
    row.payload = payload
    session.commit()
    return {"ok": True, "id": str(row.id)}


# ── Live state ────────────────────────────────────────────────────────────────

_LIVE_TTL = 20            # the plugin posts every 2 s; silent this long = the server is off
_LIVE_MAX_BYTES = 256_000


def _live_key(server: GameServer) -> str:
    return f"royale_live:{server.id}"


@plugin_router.post("/live")
async def receive_live(
    request: Request,
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    raw = await request.body()
    if len(raw) > _LIVE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Live state is too large")
    try:
        state = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Live state is not JSON") from exc
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="Live state is not an object")
    state["received_at"] = datetime.now(tz=MOSCOW).isoformat()
    RedisCacheService().set_json(_live_key(server), state, ttl_seconds=_LIVE_TTL)
    return {"ok": True}


@public_router.get("/live")
def live(server: Annotated[GameServer, Depends(resolve_server)], response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    # What the children type in «Add server»: the default port needs no number.
    address = server.host or ""
    if server.port and server.port != 25565:
        address = f"{address}:{server.port}"
    state = RedisCacheService().get_json(_live_key(server))
    if not state:
        return {"state": "offline", "server": server.slug, "address": address}
    state["server"] = server.slug
    state["address"] = address
    return state


# ── The admin panel ───────────────────────────────────────────────────────────

def _summary(row: RoyaleMatch) -> dict:
    return {
        "id": str(row.id),
        "server_slug": row.server_slug,
        "map": row.map,
        "map_title": row.map_title,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_seconds": row.duration_seconds,
        "aborted": row.aborted,
        "winner": row.winner,
        "winner_title": row.winner_title,
        "teams_count": row.teams_count,
        "players_count": row.players_count,
    }


@admin_router.get("")
def list_matches(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    include_aborted: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    q = session.query(RoyaleMatch).filter(RoyaleMatch.server_slug == server.slug)
    if not include_aborted:
        q = q.filter(RoyaleMatch.aborted.is_(False))
    rows = q.order_by(RoyaleMatch.started_at.desc().nullslast(), RoyaleMatch.created_at.desc()).limit(limit).all()
    return {"items": [_summary(r) for r in rows]}


def _get(session: Session, match_id: UUID) -> RoyaleMatch:
    row = session.get(RoyaleMatch, match_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return row


@admin_router.get("/{match_id}")
def get_match(match_id: UUID, session: Annotated[Session, Depends(get_db_session)]) -> dict:
    row = _get(session, match_id)
    return {**_summary(row), "payload": row.payload}


@admin_router.delete("/{match_id}", dependencies=[Depends(require_permission("royale.manage"))])
def delete_match(
    match_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    row = _get(session, match_id)
    record_audit(session, category="royale", action="royale.match.delete", actor=actor,
                 target_type="royale_match", target_id=str(row.id), target_label=row.map_title or row.map,
                 server_id=row.server_id, commit=False,
                 meta={"started_at": row.started_at.isoformat() if row.started_at else None, "players": row.players_count})
    session.delete(row)
    session.commit()
    return {"ok": True}


# ── Export ────────────────────────────────────────────────────────────────────

COLUMNS: list[tuple[str, str]] = [
    ("placement", "Место"),
    ("team_title", "Команда"),
    ("name", "Игрок"),
    ("status", "Итог"),
    ("kills", "Убийства"),
    ("assists", "Помощь"),
    ("deaths", "Смерти"),
    ("damage_dealt", "Урон нанёс (сердец)"),
    ("damage_taken", "Урон получил (сердец)"),
    ("healed", "Вылечился (сердец)"),
    ("blocks_broken", "Блоков сломал"),
    ("blocks_placed", "Блоков поставил"),
    ("items_picked", "Предметов собрал"),
    ("chests_opened", "Сундуков открыл"),
    ("arrows_shot", "Выстрелов из лука"),
    ("arrows_hit", "Попаданий"),
    ("food_eaten", "Съел еды"),
    ("distance", "Прошёл блоков"),
    ("alive_seconds", "Продержался"),
    ("killed_by", "Кем выбит"),
    ("killed_with", "Чем"),
]
STATUS = {"winner": "Победитель", "eliminated": "Выбыл", "left": "Вышел из игры", "playing": "В игре"}
HEARTS = {"damage_dealt", "damage_taken", "healed"}


def _cell(key: str, value: Any) -> Any:
    if value is None:
        return ""
    if key in HEARTS:
        return str(round(float(value) / 2, 1)).replace(".", ",")
    if key == "alive_seconds":
        s = int(value)
        return f"{s // 60}:{s % 60:02d}"
    if key == "status":
        return STATUS.get(str(value), value)
    return value


def _match_label(row: RoyaleMatch) -> tuple[str, str]:
    started = row.started_at.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M") if row.started_at else ""
    return started, row.map_title or row.map


def _csv(rows: list[RoyaleMatch], with_match: bool) -> Response:
    buf = io.StringIO()
    # Semicolons and a BOM: Excel in Russian opens it straight into columns, Cyrillic intact.
    writer = csv.writer(buf, delimiter=";")
    head = (["Дата", "Карта", "Победитель матча"] if with_match else []) + [title for _, title in COLUMNS]
    writer.writerow(head)
    for row in rows:
        started, map_title = _match_label(row)
        for player in row.payload.get("players") or []:
            prefix = [started, map_title, row.winner_title or ""] if with_match else []
            writer.writerow(prefix + [_cell(key, player.get(key)) for key, _ in COLUMNS])
    data = "﻿" + buf.getvalue()
    name = "royale.csv"
    if not with_match and rows:
        started, _ = _match_label(rows[0])
        name = "royale_" + started.replace(".", "-").replace(" ", "_").replace(":", "-") + ".csv"
    return Response(
        content=data.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@admin_router.get("/export/all.csv")
def export_all(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    include_aborted: bool = Query(default=False),
) -> Response:
    q = session.query(RoyaleMatch).filter(RoyaleMatch.server_slug == server.slug)
    if not include_aborted:
        q = q.filter(RoyaleMatch.aborted.is_(False))
    rows = q.order_by(RoyaleMatch.started_at.asc().nullsfirst()).all()
    return _csv(rows, with_match=True)


@admin_router.get("/{match_id}/export.csv")
def export_match(match_id: UUID, session: Annotated[Session, Depends(get_db_session)]) -> Response:
    return _csv([_get(session, match_id)], with_match=False)
