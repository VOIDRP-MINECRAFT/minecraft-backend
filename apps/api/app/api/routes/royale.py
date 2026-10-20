"""Royale (battle royale) results: the VoidRpRoyale plugin posts every finished game here,
and the admin panel lists them, shows each in full and exports them as a table for the
Academy's teaching staff (CSV that opens in Excel).

The plugin also posts the live state every couple of seconds; it lives in Redis for a short
while and the public /royale/live feeds the projector page on the site.

Game settings set in the admin panel (the team size) go back to the plugin in the answer to
that live post, so a change reaches the server within ~2 s with no restart (the team size, and
the no-fight time — changed in a running game at once). They are kept in
``game_servers.integration_settings["royale"]`` (the Royale server is temporary: no column).
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import secrets
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_any_permission, require_permission
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.royale import RoyaleMatch
from apps.api.app.models.user import User
from apps.api.app.services.redis_cache_service import RedisCacheService
from apps.api.app.utils.normalization import normalize_minecraft_nickname

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


@plugin_router.get("/leaderboard")
def plugin_leaderboard(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
    limit: int = Query(default=10, ge=1, le=30),
) -> dict:
    """All-time top players, for the hall-of-fame board the plugin shows in the lobby."""
    cache = RedisCacheService()
    key = f"royale_lb_plugin:{server.id}:{limit}"
    cached = cache.get_json(key)
    if cached:
        return cached
    rows = (
        session.query(RoyaleMatch)
        .filter(RoyaleMatch.server_slug == server.slug, RoyaleMatch.aborted.is_(False))
        .order_by(RoyaleMatch.started_at.desc().nullslast())
        .limit(2000)
        .all()
    )
    data = _standings(rows)
    out = {
        "games": data["games"],
        "players": [
            {"name": p["name"], "points": p["points"], "wins": p["wins"], "kills": p["kills"], "games": p["games"]}
            for p in data["players"][:limit]
        ],
    }
    cache.set_json(key, out, ttl_seconds=60)
    return out


# ── Portal (Origins → Royale, seamless, no re-login) ────────────────────────────
#
# A player standing in the portal on Origins is already authorised there. The Origins plugin
# mints a one-time ticket here (with Origins' secret), stores it in a cookie on the client and
# calls player.transfer() to the Royale host. The client reconnects to Royale carrying the
# cookie; the Royale plugin reads it and redeems the ticket here (with Royale's secret) to let
# the player in already authorised. The ticket is a random, single-use value kept in Redis for
# ~30 s — it cannot be forged or reused, and no cross-server signing is needed. Minting is
# limited to our own servers (not partner/external ones). Direct connections (no cookie) fall
# back to the normal login on the Royale side; nothing here touches the Origins auth.

_PORTAL_TTL = 30  # seconds a minted ticket is valid


def _portal_key(token: str) -> str:
    return f"royale_portal:{token}"


class PortalTicketIn(BaseModel):
    uuid: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=32)


@plugin_router.post("/portal-ticket")
def portal_ticket(
    body: PortalTicketIn,
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    """Origins mints a one-time portal ticket for a player it already authorised."""
    if server.is_external:
        # Only our own servers may vouch for a player's identity to Royale.
        raise HTTPException(status_code=403, detail="This server may not mint portal tickets")
    token = secrets.token_urlsafe(32)
    RedisCacheService().set_json(
        _portal_key(token),
        {
            "uuid": str(body.uuid),
            "name": body.name,
            "from_slug": server.slug,
            "from_id": str(server.id),
            "created": datetime.now(tz=MOSCOW).isoformat(),
        },
        ttl_seconds=_PORTAL_TTL,
    )
    return {"ok": True, "token": token, "ttl": _PORTAL_TTL}


class PortalRedeemIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    uuid: str | None = Field(default=None, max_length=40)


@plugin_router.post("/portal-redeem")
def portal_redeem(
    body: PortalRedeemIn,
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    """Royale redeems the ticket the client carried in its cookie. Single use."""
    cache = RedisCacheService()
    key = _portal_key(body.token)
    data = cache.get_json(key)
    if not data:
        return {"ok": False, "reason": "expired"}
    cache.delete(key)  # one-time: gone the instant it is read
    if body.uuid and str(body.uuid) != str(data.get("uuid")):
        return {"ok": False, "reason": "mismatch"}
    return {
        "ok": True,
        "uuid": data.get("uuid"),
        "name": data.get("name"),
        "from": data.get("from_slug"),
    }


def _settings(server: GameServer) -> dict:
    """What the admin panel set for this server's game ({} = the plugin's config.yml rules)."""
    raw = (server.integration_settings or {}).get("royale") or {}
    out = {}
    if isinstance(raw.get("team_size"), int) and 1 <= raw["team_size"] <= 20:
        out["team_size"] = raw["team_size"]
    if isinstance(raw.get("grace"), int) and 0 <= raw["grace"] <= 1800:
        out["grace"] = raw["grace"]
    # Event: the host starts each game. Public: games start on their own once enough gather.
    out["mode"] = "public" if raw.get("mode") == "public" else "event"
    if isinstance(raw.get("min_players"), int) and 2 <= raw["min_players"] <= 40:
        out["min_players"] = raw["min_players"]
    r = raw.get("rewards")
    if isinstance(r, dict):
        out["rewards"] = {
            "enabled": bool(r.get("enabled")),
            "coins_win": int(r.get("coins_win") or 0),
            "coins_kill": int(r.get("coins_kill") or 0),
            "coins_placement": {str(k): int(v) for k, v in (r.get("coins_placement") or {}).items()
                                if str(k).isdigit() and 1 <= int(k) <= 8},
        }
    return out


@public_router.get("/leaderboard")
def leaderboard(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    response: Response,
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    """All-time standings from every finished game: top players by points, wins, kills."""
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["Access-Control-Allow-Origin"] = "*"
    cache = RedisCacheService()
    key = f"royale_leaderboard:{server.id}:{limit}"
    cached = cache.get_json(key)
    if cached:
        return cached
    rows = (
        session.query(RoyaleMatch)
        .filter(RoyaleMatch.server_slug == server.slug, RoyaleMatch.aborted.is_(False))
        .order_by(RoyaleMatch.started_at.desc().nullslast())
        .limit(2000)
        .all()
    )
    data = _standings(rows)
    out = {
        "games": data["games"],
        "players": data["players"][:limit],
        "place_points": PLACE_POINTS,
        "kill_points": KILL_POINTS,
        "server": server.slug,
    }
    cache.set_json(key, out, ttl_seconds=60)
    return out


def _profile_payload(session: Session, server: GameServer, nick: str) -> dict:
    cache = RedisCacheService()
    _, normalized = normalize_minecraft_nickname(nick)
    key = f"royale_profile:{server.id}:{normalized}"
    cached = cache.get_json(key)
    if cached:
        return cached
    rows = (
        session.query(RoyaleMatch)
        .filter(RoyaleMatch.server_slug == server.slug, RoyaleMatch.aborted.is_(False))
        .order_by(RoyaleMatch.started_at.desc().nullslast())
        .limit(5000)
        .all()
    )
    prof = _player_profile(rows, nick)
    ranked = _standings(rows)["players"]
    prof["rank"] = next((i + 1 for i, p in enumerate(ranked)
                         if normalize_minecraft_nickname(str(p["name"]))[1] == normalized), None)
    prof["total_players"] = len(ranked)
    prof["server"] = server.slug
    cache.set_json(key, prof, ttl_seconds=60)
    return prof


@public_router.get("/profile/{nick}")
def public_profile(
    nick: str,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    response: Response,
) -> dict:
    """One player's all-time Royale profile — level, wins, kills, rank — for the site and game."""
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return _profile_payload(session, server, nick)


@plugin_router.get("/profile/{nick}")
def plugin_profile(
    nick: str,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    """The player's Royale profile for the in-game /stats card."""
    return _profile_payload(session, server, nick)


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
    saved = _settings(server)
    running = live_state.get("state") in ("freeze", "running")
    return {
        "team_size": saved.get("team_size"),
        "current": current if isinstance(current, int) else None,
        "grace": saved.get("grace"),
        "mode": saved["mode"],
        "current_mode": live_state.get("mode"),
        "min_players": saved.get("min_players"),
        "current_grace": live_state.get("grace") if isinstance(live_state.get("grace"), int) else None,
        "grace_left": live_state.get("grace_left") if running else None,
        "online": bool(live_state),
        "in_game": live_state.get("state") not in (None, "lobby", "countdown"),
        "maps": maps,
        "map": current_map or live_state.get("map"),
        "rewards": saved.get("rewards") or {"enabled": False, "coins_win": 0, "coins_kill": 0, "coins_placement": {}},
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


class RoyaleRewardsIn(BaseModel):
    enabled: bool | None = None
    coins_win: int | None = Field(default=None, ge=0, le=100000)
    coins_kill: int | None = Field(default=None, ge=0, le=100000)
    coins_placement: dict[str, int] | None = None


class RoyaleSettingsIn(BaseModel):
    team_size: int | None = Field(default=None, ge=1, le=20)
    grace: int | None = Field(default=None, ge=0, le=1800)  # no-fight seconds at a game's start
    mode: str | None = Field(default=None, pattern="^(event|public)$")
    min_players: int | None = Field(default=None, ge=2, le=40)  # auto-start threshold in public mode
    rewards: RoyaleRewardsIn | None = None  # Void Coin payouts, set from the admin


@admin_router.put("/settings", dependencies=[Depends(require_any_permission("royale.control", "royale.manage"))])
def put_settings(
    body: RoyaleSettingsIn,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    before = _settings(server)
    royale = dict((server.integration_settings or {}).get("royale") or {})
    meta: dict[str, Any] = {}
    if body.team_size is not None:
        royale["team_size"] = body.team_size
        meta["team_size"] = [before.get("team_size"), body.team_size]
    if body.grace is not None:
        royale["grace"] = body.grace
        meta["grace"] = [before.get("grace"), body.grace]
    if body.mode is not None:
        royale["mode"] = body.mode
        meta["mode"] = [before.get("mode"), body.mode]
    if body.min_players is not None:
        royale["min_players"] = body.min_players
        meta["min_players"] = [before.get("min_players"), body.min_players]
    if body.rewards is not None:
        r = dict(royale.get("rewards") or {})
        if body.rewards.enabled is not None:
            r["enabled"] = body.rewards.enabled
        if body.rewards.coins_win is not None:
            r["coins_win"] = body.rewards.coins_win
        if body.rewards.coins_kill is not None:
            r["coins_kill"] = body.rewards.coins_kill
        if body.rewards.coins_placement is not None:
            r["coins_placement"] = {str(k): int(v) for k, v in body.rewards.coins_placement.items()
                                    if str(k).isdigit() and 1 <= int(k) <= 8 and 0 <= int(v) <= 100000}
        royale["rewards"] = r
        meta["rewards"] = [before.get("rewards"), r]
    if not meta:
        raise HTTPException(status_code=400, detail="Нечего менять")
    integration = dict(server.integration_settings or {})
    integration["royale"] = royale
    server.integration_settings = integration
    record_audit(session, category="royale", action="royale.settings", actor=actor,
                 target_type="server", target_id=server.slug, target_label=server.name,
                 server_id=server.id, commit=False, meta=meta)
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
    "team": "перевод в команду", "join": "добавил в игру", "announce": "объявление", "mute": "мут", "unmute": "снят мут",
    "kick": "кик", "map": "карта следующей игры",
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
    text: str | None = Field(default=None, max_length=160)


def _command_line(body: RoyaleCommandIn) -> str:
    if body.action in _GAME_ACTIONS:
        return _GAME_ACTIONS[body.action]
    if body.action == "map":
        if not body.map or not _MAP_ID.match(body.map):
            raise HTTPException(status_code=400, detail="Unknown map")
        return f"br map use {body.map}"
    if body.action == "announce":
        text = _clean_text(body.text)
        if not text:
            raise HTTPException(status_code=400, detail="Пустое объявление")
        return f"br say {text}"
    if body.action not in ("team", "join", "mute", "unmute", "kick"):
        raise HTTPException(status_code=400, detail="Unknown action")
    if not body.player or not _NICK.match(body.player):
        raise HTTPException(status_code=400, detail="Player nickname is required")
    if body.action in ("team", "join"):
        team = (body.team or "").lower()
        if body.action == "join" and team not in _COLORS:
            raise HTTPException(status_code=400, detail="Для добавления в игру выберите команду")
        if team != "none" and team not in _COLORS:
            raise HTTPException(status_code=400, detail="Unknown team colour")
        return f"br {body.action} {body.player} {team}"
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


def _clean_text(text: str | None) -> str:
    """A host's announcement: one line, no colour codes or MiniMessage tags, trimmed."""
    out = (text or "").replace("\n", " ").replace("\r", " ")
    out = out.replace("§", "").replace("<", "").replace(">", "")
    return re.sub(r"\s+", " ", out).strip()[:120]


@admin_router.get("/readiness")
def readiness(server: Annotated[GameServer, Depends(resolve_server)],
              session: Annotated[Session, Depends(get_db_session)]) -> dict:
    """A pre-event checklist that checks itself: whitelist, test matches, a running game, the
    load-test stand and bots. Each item: ok True/False/None (unknown) with a short hint."""
    live_state = RedisCacheService().get_json(_live_key(server)) or {}
    online = bool(live_state)
    state = live_state.get("state")
    checks = []

    checks.append({"key": "online", "label": "Сервер на связи",
                   "ok": online, "detail": None if online else "состояние не приходит",
                   "hint": "Запустите сервер Royale." if not online else None})

    wl = _whitelist_on(server)
    checks.append({"key": "whitelist", "label": "Вайтлист выключен (дети зайдут)",
                   "ok": (wl is False) if wl is not None else None,
                   "detail": "включён — пустит только по списку" if wl else None,
                   "hint": "Кнопка «Выключить вайтлист» на Пульте." if wl else None})

    running = state in ("freeze", "running", "countdown")
    checks.append({"key": "no_game", "label": "Игра не идёт",
                   "ok": (not running) if online else None,
                   "detail": "сейчас идёт игра" if running else None,
                   "hint": "Дождитесь конца или остановите игру." if running else None})

    aborted = session.query(RoyaleMatch).filter(RoyaleMatch.server_slug == server.slug, RoyaleMatch.aborted.is_(True)).count()
    checks.append({"key": "test_matches", "label": "Тестовые матчи убраны",
                   "ok": aborted == 0, "detail": f"остановленных матчей: {aborted}" if aborted else None,
                   "hint": "Вкладка «Матчи» → «Удалить их»." if aborted else None})

    stand = _stand_processes()
    checks.append({"key": "stand", "label": "Стенд и боты выключены",
                   "ok": not stand, "detail": (", ".join(stand) if stand else None),
                   "hint": "Остановите тестовый клиент и ботов нагрузки." if stand else None})

    ready = all(c["ok"] for c in checks if c["ok"] is not None) and not any(c["ok"] is None for c in checks[:1])
    return {"ready": ready, "online": online, "players": live_state.get("online") if online else None, "checks": checks}


# Interpreters only, so a shell or a grep that merely mentions these names is not mistaken
# for the thing itself (the admin panel's own tooling runs in shells).
_RUNTIMES = {"java", "node", "nodejs", "python", "python3", "xvfb"}


def _stand_processes() -> list[str]:
    """Load-test / headless-client processes still running on this box (temp Royale server)."""
    import psutil

    found: set[str] = set()
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmd = " ".join(proc.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name not in _RUNTIMES:
            continue
        if name == "xvfb" and ":99" in cmd:
            found.add("экран стенда (Xvfb)")
        elif "loadtest.js" in cmd or "opener.js" in cmd:
            found.add("боты нагрузки")
        elif "portablemc" in cmd or "/mcclient/" in cmd:
            found.add("тестовый клиент")
    return sorted(found)


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


# ── Dashboard, analytics, players (the big admin tab) ───────────────────────────

def _server_rows(session: Session, server: GameServer, limit: int = 5000) -> list[RoyaleMatch]:
    return (
        session.query(RoyaleMatch)
        .filter(RoyaleMatch.server_slug == server.slug, RoyaleMatch.aborted.is_(False))
        .order_by(RoyaleMatch.started_at.desc().nullslast())
        .limit(limit)
        .all()
    )


def _mday(row: RoyaleMatch) -> date | None:
    return row.started_at.astimezone(MOSCOW).date() if row.started_at else None


@admin_router.get("/overview")
def royale_overview(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    """The dashboard: live state, headline numbers, recent games and the top players."""
    live = RedisCacheService().get_json(_live_key(server)) or {}
    rows = _server_rows(session, server)
    std = _standings(rows)
    for p in std["players"]:
        p["level"] = _level(int(p.get("points") or 0))
    today = datetime.now(tz=MOSCOW).date()
    week = today - timedelta(days=7)
    games_today = sum(1 for r in rows if _mday(r) == today)
    games_week = sum(1 for r in rows if (_mday(r) or date.min) >= week)
    durations = [r.duration_seconds for r in rows if r.duration_seconds]
    kills = sum(int(p.get("kills") or 0) for p in std["players"])
    saved = _settings(server)
    state = live.get("state")
    return {
        "online": live.get("online") or 0,
        "state": state,
        "live_map": live.get("map"),
        "countdown": live.get("countdown"),
        "in_game": state not in (None, "lobby", "countdown"),
        "server_online": bool(live),
        "totals": {
            "games": len(rows),
            "players": len(std["players"]),
            "kills": kills,
            "games_today": games_today,
            "games_week": games_week,
            "avg_duration": round(sum(durations) / len(durations)) if durations else 0,
        },
        "recent": [_summary(r) for r in rows[:8]],
        "top": std["players"][:6],
        "settings": {
            "mode": saved.get("mode"),
            "team_size": saved.get("team_size"),
            "min_players": saved.get("min_players"),
            "grace": saved.get("grace"),
            "rewards_on": bool((saved.get("rewards") or {}).get("enabled")),
        },
    }


@admin_router.get("/analytics")
def royale_analytics(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    days: int = Query(default=30, ge=7, le=120),
) -> dict:
    """Charts: games and players per day, map popularity, team-size split, duration, placements."""
    rows = _server_rows(session, server)
    today = datetime.now(tz=MOSCOW).date()
    start = today - timedelta(days=days - 1)
    per_day: dict[str, dict] = {}
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        per_day[d] = {"date": d, "games": 0, "players": 0, "kills": 0}
    maps: dict[str, int] = {}
    team_sizes: dict[str, int] = {}
    player_counts: dict[str, int] = {}
    durations: list[int] = []
    for r in rows:
        d = _mday(r)
        if d and d.isoformat() in per_day:
            cell = per_day[d.isoformat()]
            cell["games"] += 1
            cell["players"] += int(r.players_count or 0)
            cell["kills"] += sum(int(p.get("kills") or 0) for p in (r.payload or {}).get("players") or [])
        title = r.map_title or r.map or "—"
        maps[title] = maps.get(title, 0) + 1
        pc = int(r.players_count or 0)
        if pc:
            player_counts[str(pc)] = player_counts.get(str(pc), 0) + 1
        teams = (r.payload or {}).get("teams") or []
        if teams:
            avg_team = round((r.players_count or 0) / max(1, len(teams)))
            team_sizes[str(avg_team)] = team_sizes.get(str(avg_team), 0) + 1
        if r.duration_seconds:
            durations.append(r.duration_seconds)
    return {
        "days": list(per_day.values()),
        "maps": sorted(({"name": k, "count": v} for k, v in maps.items()), key=lambda x: -x["count"]),
        "team_sizes": sorted(({"size": k, "count": v} for k, v in team_sizes.items()), key=lambda x: int(x["size"])),
        "player_counts": sorted(({"players": k, "count": v} for k, v in player_counts.items()), key=lambda x: int(x["players"])),
        "duration_avg": round(sum(durations) / len(durations)) if durations else 0,
        "duration_max": max(durations) if durations else 0,
        "games": len(rows),
    }


@admin_router.get("/players")
def royale_players(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    q: str | None = Query(default=None),
    sort: str = Query(default="points"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """All players with their aggregate stats — searchable, sortable (the players tab)."""
    rows = _server_rows(session, server)
    players = _standings(rows)["players"]
    for i, p in enumerate(players):
        p["rank"] = i + 1
        p["level"] = _level(int(p.get("points") or 0))
        d = int(p.get("deaths") or 0)
        p["kd"] = round(int(p.get("kills") or 0) / d, 2) if d else float(p.get("kills") or 0)
        p["win_rate"] = round(p["wins"] / p["games"], 3) if p.get("games") else 0.0
    if q:
        ql = q.strip().lower()
        players = [p for p in players if ql in str(p["name"]).lower()]
    keys = {"points": lambda p: -p["points"], "kills": lambda p: -p["kills"], "wins": lambda p: -p["wins"],
            "games": lambda p: -p["games"], "name": lambda p: str(p["name"]).lower()}
    players = sorted(players, key=keys.get(sort, keys["points"]))
    return {"players": players[:limit], "total": len(players)}


@admin_router.get("/player/{nick}")
def royale_player(
    nick: str,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    """One player: full profile, their match history, and their Void Coin balance."""
    _, normalized = normalize_minecraft_nickname(nick)
    rows = _server_rows(session, server)
    prof = _player_profile(rows, nick)
    ranked = _standings(rows)["players"]
    prof["rank"] = next((i + 1 for i, p in enumerate(ranked)
                        if normalize_minecraft_nickname(str(p["name"]))[1] == normalized), None)
    prof["total_players"] = len(ranked)
    history = []
    for r in rows:
        line = next((p for p in (r.payload or {}).get("players") or []
                    if normalize_minecraft_nickname(str(p.get("name") or ""))[1] == normalized), None)
        if line:
            history.append({**_summary(r), "placement": line.get("placement"), "kills": line.get("kills"),
                            "team_title": line.get("team_title")})
        if len(history) >= 25:
            break
    account = session.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == normalized)
    ).scalar_one_or_none()
    prof["void_coins"] = int(account.void_coins or 0) if account else None
    prof["has_account"] = account is not None
    prof["history"] = history
    return prof


class RoyalePlayerAction(BaseModel):
    action: str = Field(pattern="^(kick|ban|unban|grant_coins)$")
    amount: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    reason: str | None = Field(default=None, max_length=200)


@admin_router.post("/player/{nick}/action", dependencies=[Depends(require_permission("royale.manage"))])
def royale_player_action(
    nick: str,
    body: RoyalePlayerAction,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    """Moderate a Royale player: kick, ban/unban on the Royale server, or grant Void Coins."""
    safe = re.sub(r"[^A-Za-z0-9_]", "", nick)[:16]
    if not safe:
        raise HTTPException(status_code=400, detail="Плохой ник")
    answer = ""
    if body.action == "grant_coins":
        amount = int(body.amount or 0)
        _, normalized = normalize_minecraft_nickname(nick)
        account = session.execute(
            select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == normalized)
        ).scalar_one_or_none()
        if account is None:
            raise HTTPException(status_code=404, detail="Нет аккаунта у игрока")
        account.void_coins = max(0, int(account.void_coins or 0) + amount)
        session.flush()
        answer = f"Баланс: {account.void_coins} Void Coins"
    else:
        reason = (body.reason or "Нарушение правил").replace('"', "'")[:120]
        cmd = {
            "kick": f"minecraft:kick {safe} {reason}",
            "ban": f"minecraft:ban {safe} {reason}",
            "unban": f"minecraft:pardon {safe}",
        }[body.action]
        try:
            answer = server_ops.strip_color_codes(server_ops.rcon_command(server, cmd, timeout=5.0))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Сервер не ответил: {exc}") from exc
    record_audit(session, category="royale", action=f"royale.player.{body.action}", actor=actor,
                 target_type="player", target_id=safe, target_label=safe,
                 server_id=server.id, commit=False, meta={"amount": body.amount, "reason": body.reason})
    session.commit()
    return {"ok": True, "answer": answer or "Готово"}


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


def _level(xp: int) -> int:
    """A gentle progression curve: level grows with the square root of total points."""
    return int(math.sqrt(max(0, xp) / 25.0)) + 1


def _player_profile(rows: list[RoyaleMatch], nick: str) -> dict:
    """Aggregate one player's all-time Royale stats across their finished games."""
    _, normalized = normalize_minecraft_nickname(nick)
    name = nick
    games = wins = top3 = kills = deaths = assists = chests = alive = points = 0
    damage = 0.0
    best: int | None = None
    for row in rows:
        for p in (row.payload or {}).get("players") or []:
            pn = str(p.get("name") or "")
            if not pn or normalize_minecraft_nickname(pn)[1] != normalized:
                continue
            name = pn
            place, k = int(p.get("placement") or 0), int(p.get("kills") or 0)
            games += 1
            kills += k
            deaths += int(p.get("deaths") or 0)
            assists += int(p.get("assists") or 0)
            chests += int(p.get("chests_opened") or 0)
            alive += int(p.get("alive_seconds") or 0)
            damage += float(p.get("damage_dealt") or 0)
            points += int(p["points"]) if p.get("points") is not None else _points(place, k)
            if place == 1:
                wins += 1
            if 1 <= place <= 3:
                top3 += 1
            if place > 0:
                best = place if best is None else min(best, place)
    return {
        "name": name,
        "exists": games > 0,
        "games": games,
        "wins": wins,
        "top3": top3,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kd": round(kills / deaths, 2) if deaths else float(kills),
        "damage": round(damage, 1),
        "chests": chests,
        "points": points,
        "best_place": best,
        "win_rate": round(wins / games, 3) if games else 0.0,
        "playtime_seconds": alive,
        "level": _level(points),
        "xp": points,
        "next_level_xp": int((_level(points) ** 2) * 25),
    }


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
                                            "deaths": 0, "assists": 0, "games": 0, "damage": 0.0, "alive_seconds": 0, "best_place": None})
            agg["points"] += int(p["points"]) if p.get("points") is not None else _points(place, kills)
            agg["kills"] += kills
            agg["deaths"] += int(p.get("deaths") or 0)
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
