"""Royale (battle royale) results: the VoidRpRoyale plugin posts every finished game here,
and the admin panel lists them, shows each in full and exports them as a table for the
Academy's teaching staff (CSV that opens in Excel).

The plugin also posts the live state every couple of seconds; it lives in Redis for a short
while and the public /royale/live feeds the projector page on the site.

Game settings set in the admin panel (the team size) go back to the plugin in the answer to
that live post, so a change reaches the server within ~2 s with no restart. They are kept in
``game_servers.integration_settings["royale"]`` (the Royale server is temporary: no column).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
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
    wanted = _settings(server)
    return {"ok": True, "settings": wanted} if wanted else {"ok": True}


def _settings(server: GameServer) -> dict:
    """What the admin panel set for this server's game ({} = the plugin's config.yml rules)."""
    raw = (server.integration_settings or {}).get("royale") or {}
    out = {}
    if isinstance(raw.get("team_size"), int) and 1 <= raw["team_size"] <= 20:
        out["team_size"] = raw["team_size"]
    return out


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


# Declared before /{match_id}: that one would take "settings" (or "live", "aborted") for an id.

@admin_router.get("/settings")
def royale_settings(server: Annotated[GameServer, Depends(resolve_server)]) -> dict:
    """The team size set here, and what the server runs now (from its live state)."""
    live_state = RedisCacheService().get_json(_live_key(server)) or {}
    current = live_state.get("team_size")
    maps, current_map = _maps(server) if live_state else ([], None)
    return {
        "team_size": _settings(server).get("team_size"),
        "current": current if isinstance(current, int) else None,
        "online": bool(live_state),
        "in_game": live_state.get("state") not in (None, "lobby", "countdown"),
        "maps": maps,
        "map": current_map or live_state.get("map"),
    }


def _maps(server: GameServer) -> tuple[list[str], str | None]:
    """The arenas the plugin has, from «/br map»: "Карты: a, b (сейчас a)"."""
    try:
        out = server_ops.strip_color_codes(server_ops.rcon_command(server, "br map", timeout=4.0))
    except Exception:  # noqa: BLE001 — the panel just shows no list
        return [], None
    m = re.search(r"Карты:\s*(.*?)\s*\(сейчас\s+([^)]+)\)", out)
    if not m:
        return [], None
    return [x.strip() for x in m.group(1).split(",") if x.strip()], m.group(2).strip()


class RoyaleSettingsIn(BaseModel):
    team_size: int = Field(ge=1, le=20)


@admin_router.put("/settings", dependencies=[Depends(require_permission("royale.manage"))])
def put_settings(
    body: RoyaleSettingsIn,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    before = _settings(server).get("team_size")
    integration = dict(server.integration_settings or {})
    integration["royale"] = {**(integration.get("royale") or {}), "team_size": body.team_size}
    server.integration_settings = integration
    record_audit(session, category="royale", action="royale.settings", actor=actor,
                 target_type="server", target_id=server.slug, target_label=server.name,
                 server_id=server.id, commit=False, meta={"team_size": [before, body.team_size]})
    session.commit()
    return royale_settings(server)


# ── The host panel: the game driven from the admin panel ─────────────────────
# Through the plugin's own commands over RCON (what the host types in game), so nothing on the
# server changes for it. Only the actions below; a nickname and a colour are checked first.

_NICK = re.compile(r"^[A-Za-z0-9_]{1,16}$")
_MAP_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_COLORS = {"red", "blue", "green", "yellow", "orange", "purple", "aqua", "pink"}
_GAME_ACTIONS = {
    "start": "br start",
    "start_force": "br start force",
    "again": "br again",
    "stop": "br stop",
    "pause": "br pause",
    "resume": "br resume",
    "phase": "br phase",
    "drop": "br drop",
    "clearresults": "br clearresults",
    "whitelist_on": "whitelist on",
    "whitelist_off": "whitelist off",
}
_ACTION_LABELS = {
    "start": "старт игры", "start_force": "старт без проверок", "again": "игра заново", "stop": "остановка игры",
    "pause": "пауза", "resume": "продолжение", "phase": "следующая фаза", "drop": "припасы сейчас",
    "clearresults": "итоги в архив", "whitelist_on": "вайтлист включён", "whitelist_off": "вайтлист выключен",
    "team": "перевод в команду", "mute": "мут", "unmute": "снят мут", "kick": "кик", "map": "карта следующей игры",
}


def _whitelist_on(server: GameServer) -> bool | None:
    """From server.properties (the server writes it there on /whitelist on|off)."""
    path = os.path.join(server_ops.resolve_data_dir(server) or "", "server.properties")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("white-list="):
                    return line.strip().split("=", 1)[1].lower() == "true"
    except OSError:
        return None
    return None


def _online(server: GameServer) -> list[str] | None:
    try:
        out = server_ops.strip_color_codes(server_ops.rcon_command(server, "list", timeout=3.0))
    except Exception:  # noqa: BLE001 — offline or RCON closed: no list
        return None
    names = out.split(":", 1)[1] if ":" in out else ""
    return sorted((n.strip() for n in names.split(",") if _NICK.match(n.strip())), key=str.lower)


@admin_router.get("/live")
def admin_live(server: Annotated[GameServer, Depends(resolve_server)], players: bool = Query(default=True)) -> dict:
    """The live state (what the projector shows) plus what the host panel needs: the whitelist
    and who is online (by RCON, only when asked — the panel asks every few seconds)."""
    state = RedisCacheService().get_json(_live_key(server)) or {"state": "offline"}
    state["whitelist"] = _whitelist_on(server)
    if players:
        state["players"] = _online(server) if state.get("state") != "offline" else []
    return state


class RoyaleCommandIn(BaseModel):
    action: str = Field(max_length=32)
    player: str | None = Field(default=None, max_length=16)
    team: str | None = Field(default=None, max_length=16)
    minutes: int | None = Field(default=None, ge=1, le=120)
    map: str | None = Field(default=None, max_length=32)


def _command_line(body: RoyaleCommandIn) -> str:
    if body.action in _GAME_ACTIONS:
        return _GAME_ACTIONS[body.action]
    if body.action == "map":
        if not body.map or not _MAP_ID.match(body.map):
            raise HTTPException(status_code=400, detail="Unknown map")
        return f"br map use {body.map}"
    if body.action not in ("team", "mute", "unmute", "kick"):
        raise HTTPException(status_code=400, detail="Unknown action")
    if not body.player or not _NICK.match(body.player):
        raise HTTPException(status_code=400, detail="Player nickname is required")
    if body.action == "team":
        team = (body.team or "").lower()
        if team != "none" and team not in _COLORS:
            raise HTTPException(status_code=400, detail="Unknown team colour")
        return f"br team {body.player} {team}"
    if body.action == "mute":
        return f"br mute {body.player} {body.minutes or 5}"
    if body.action == "unmute":
        return f"br unmute {body.player}"
    return f"kick {body.player} Ведущий отключил тебя от сервера. Можно зайти снова."


@admin_router.post("/command", dependencies=[Depends(require_permission("royale.control"))])
def admin_command(
    body: RoyaleCommandIn,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    line = _command_line(body)
    try:
        out = server_ops.strip_color_codes(server_ops.rcon_command(server, line, timeout=8.0)).strip()
    except Exception as exc:  # noqa: BLE001 — the host sees why
        raise HTTPException(status_code=502, detail=f"Сервер не ответил: {exc}") from exc
    out = re.sub(r"^Royale:\s*", "", out)
    record_audit(session, category="royale", action="royale.command", actor=actor,
                 target_type="server", target_id=server.slug, target_label=_ACTION_LABELS.get(body.action, body.action),
                 server_id=server.id, meta={"command": line, "answer": out[:300]})
    return {"ok": True, "command": line, "answer": out or "Готово"}


@admin_router.delete("/aborted", dependencies=[Depends(require_permission("royale.manage"))])
def delete_aborted(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    """Every stopped match of this server (test games) at once."""
    rows = session.query(RoyaleMatch).filter(RoyaleMatch.server_slug == server.slug, RoyaleMatch.aborted.is_(True)).all()
    for row in rows:
        session.delete(row)
    record_audit(session, category="royale", action="royale.match.delete_aborted", actor=actor,
                 target_type="server", target_id=server.slug, target_label=server.name,
                 server_id=server.id, commit=False, meta={"deleted": len(rows)})
    session.commit()
    return {"ok": True, "deleted": len(rows)}


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


# ── The day's standings ───────────────────────────────────────────────────────
# Points for a team's place and for a kill, as the plugin's day-points default. A match saved by
# a newer plugin carries its own points per team and player; these are for the older ones.

PLACE_POINTS = [10, 6, 5, 4, 3, 2, 1, 1]
KILL_POINTS = 1


def _points(place: int, kills: int) -> int:
    base = PLACE_POINTS[place - 1] if 1 <= place <= len(PLACE_POINTS) else 0
    return base + kills * KILL_POINTS


def _day(text: str | None) -> date:
    if not text:
        return datetime.now(tz=MOSCOW).date()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD") from exc


def _day_matches(session: Session, server: GameServer, day: date) -> list[RoyaleMatch]:
    start = datetime.combine(day, time.min, tzinfo=MOSCOW)
    return (
        session.query(RoyaleMatch)
        .filter(
            RoyaleMatch.server_slug == server.slug,
            RoyaleMatch.aborted.is_(False),
            RoyaleMatch.started_at >= start,
            RoyaleMatch.started_at < start + timedelta(days=1),
        )
        .order_by(RoyaleMatch.started_at.asc())
        .all()
    )


def _standings(rows: list[RoyaleMatch]) -> dict:
    teams: dict[str, dict] = {}
    players: dict[str, dict] = {}
    for row in rows:
        payload = row.payload or {}
        for t in payload.get("teams") or []:
            key = str(t.get("color") or "")
            if not key:
                continue
            place, kills = int(t.get("placement") or 0), int(t.get("kills") or 0)
            agg = teams.setdefault(key, {"color": key, "title": t.get("title") or key, "points": 0, "wins": 0, "kills": 0, "games": 0})
            agg["points"] += int(t["points"]) if t.get("points") is not None else _points(place, kills)
            agg["kills"] += kills
            agg["games"] += 1
            agg["wins"] += 1 if place == 1 else 0
        for p in payload.get("players") or []:
            name = str(p.get("name") or "")
            if not name:
                continue
            place, kills = int(p.get("placement") or 0), int(p.get("kills") or 0)
            agg = players.setdefault(name, {"name": name, "team": None, "team_title": None, "points": 0, "wins": 0, "kills": 0,
                                            "assists": 0, "games": 0, "damage": 0.0, "alive_seconds": 0, "best_place": None})
            agg["points"] += int(p["points"]) if p.get("points") is not None else _points(place, kills)
            agg["kills"] += kills
            agg["assists"] += int(p.get("assists") or 0)
            agg["games"] += 1
            agg["wins"] += 1 if place == 1 else 0
            agg["damage"] += float(p.get("damage_dealt") or 0)
            agg["alive_seconds"] += int(p.get("alive_seconds") or 0)
            if place > 0:
                agg["best_place"] = place if agg["best_place"] is None else min(agg["best_place"], place)
            agg["team"], agg["team_title"] = p.get("team"), p.get("team_title")
    order = lambda r: (-r["points"], -r["wins"], -r["kills"])  # noqa: E731
    return {
        "games": len(rows),
        "matches": [_summary(r) for r in rows],
        "teams": sorted(teams.values(), key=order),
        "players": sorted(players.values(), key=lambda r: (-r["points"], -r["kills"], r["name"])),
        "place_points": PLACE_POINTS,
        "kill_points": KILL_POINTS,
    }


@admin_router.get("/standings/day")
def day_standings(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    day: str | None = Query(default=None, alias="date"),
) -> dict:
    d = _day(day)
    return {"date": d.isoformat(), **_standings(_day_matches(session, server, d))}


@admin_router.get("/standings/all")
def all_standings(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    """Every finished game of this server, added up — the «Игроки» tab."""
    rows = (session.query(RoyaleMatch)
            .filter(RoyaleMatch.server_slug == server.slug, RoyaleMatch.aborted.is_(False))
            .order_by(RoyaleMatch.started_at.asc()).all())
    out = _standings(rows)
    out.pop("matches", None)
    return out


@admin_router.get("/standings/day.csv")
def day_standings_csv(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    day: str | None = Query(default=None, alias="date"),
) -> Response:
    d = _day(day)
    data = _standings(_day_matches(session, server, d))
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([f"Итоги дня {d.strftime('%d.%m.%Y')}", f"игр: {data['games']}",
                     "очки за место: " + "/".join(map(str, PLACE_POINTS)), f"за убийство: {KILL_POINTS}"])
    writer.writerow([])
    writer.writerow(["Место", "Команда", "Очки", "Побед", "Убийств", "Игр"])
    for i, t in enumerate(data["teams"], 1):
        writer.writerow([i, t["title"], t["points"], t["wins"], t["kills"], t["games"]])
    writer.writerow([])
    writer.writerow(["Место", "Игрок", "Команда (последняя игра)", "Очки", "Побед", "Убийств", "Помощь", "Игр"])
    for i, p in enumerate(data["players"], 1):
        writer.writerow([i, p["name"], p["team_title"] or "", p["points"], p["wins"], p["kills"], p["assists"], p["games"]])
    return Response(
        content=("\ufeff" + buf.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="royale_day_{d.isoformat()}.csv"'},
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
