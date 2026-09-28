"""Travelling trader endpoints: game server (NPC, trades), WebGUI page (only via the NPC), HUD info."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_stat_cache import PlayerStatCache
from apps.api.app.models.trader import TraderTransaction, TraderVisit
from apps.api.app.services.trader_service import TraderError, TraderService

plugin_router = APIRouter(prefix="/game-sync/trader", tags=["game-sync", "trader"])
ui_router = APIRouter(prefix="/game-ui/trader", tags=["game-ui", "trader"])


def _fail(exc: TraderError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


# ── game server ──────────────────────────────────────────────────────────────
class TickRequest(BaseModel):
    online: list[str] = Field(default_factory=list, max_length=500)


@plugin_router.post("/tick")
def tick(
    payload: TickRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Polled by the plugin every few seconds: whether the NPC should stand at spawn, and where.
    Also sends the WebGUI announcements to the players currently online."""
    service = TraderService(db, server.id)
    cfg = service.config()
    service.expire_stale()
    service.announce(payload.online)
    visit = service.active_visit()
    next_start = service.next_visit_start() if visit is None else None
    db.commit()
    return {
        "enabled": cfg.enabled,
        "active": None if visit is None else {
            "visit_id": str(visit.id),
            "kind": visit.kind,
            "ends_at": _iso(visit.ends_at),
        },
        "next_starts_at": _iso(next_start),
        "duration_minutes": cfg.duration_minutes,
        "interval_minutes": cfg.interval_minutes,
        "spawn": cfg.spawn.model_dump(),
        "interact_radius": cfg.interact_radius,
    }


class OpenRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=16)


@plugin_router.post("/open")
def open_session(
    payload: OpenRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """The player right-clicked the trader: allow the trade page for a while."""
    service = TraderService(db, server.id)
    try:
        session = service.open_session(payload.player_name)
    except TraderError as exc:
        return {"ok": False, "message": str(exc)}
    db.commit()
    return {"ok": True, "expires_at": _iso(session.expires_at)}


class ResultRequest(BaseModel):
    ok: bool
    qty_done: int = Field(default=0, ge=0, le=6400)
    error: str | None = Field(default=None, max_length=500)


@plugin_router.post("/transactions/{tx_id}/result")
def trade_result(
    tx_id: UUID,
    payload: ResultRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    service = TraderService(db, server.id)
    try:
        tx = service.complete_trade(tx_id, payload.ok, payload.qty_done, payload.error)
    except TraderError as exc:
        raise _fail(exc)
    db.commit()
    return {"ok": True, "status": tx.status, "qty_done": tx.qty_done}


class SpawnRequest(BaseModel):
    world: str = Field(min_length=1, max_length=64)
    x: float
    y: float
    z: float
    yaw: float = 0.0
    set_by: str | None = Field(default=None, max_length=16)


@plugin_router.post("/spawn")
def set_spawn(
    payload: SpawnRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """``/vrgs trader here`` from an operator in game: the NPC will stand where they stand."""
    service = TraderService(db, server.id)
    cfg = service.config()
    cfg.spawn = cfg.spawn.model_validate({"world": payload.world, "x": payload.x, "y": payload.y, "z": payload.z, "yaw": payload.yaw})
    service.save_config(cfg, payload.set_by or "game")
    db.commit()
    return {"ok": True, "spawn": cfg.spawn.model_dump()}


# ── WebGUI page ──────────────────────────────────────────────────────────────
def _tx_out(tx: TraderTransaction) -> dict:
    return {
        "id": str(tx.id),
        "stock_id": str(tx.stock_id),
        "side": tx.side,
        "item_key": tx.item_key,
        "qty_requested": tx.qty_requested,
        "qty_done": tx.qty_done,
        "unit_price": tx.unit_price,
        "total": tx.total,
        "status": tx.status,
        "error": tx.error,
        "created_at": _iso(tx.created_at),
    }


def _active_with_session(service: TraderService, player: PlayerAccount) -> TraderVisit:
    visit = service.active_visit(create=False)
    if visit is None:
        raise HTTPException(status_code=404, detail="Скупщик ушёл. Он регулярно приходит на спавн — следите за уведомлениями.")
    if not service.has_session(player.minecraft_nickname, visit):
        raise HTTPException(status_code=403, detail="Торговля открывается только у скупщика: подойдите к нему на спавне и нажмите правой кнопкой.")
    return visit


def _state(db: Session, server: GameServer, service: TraderService, visit: TraderVisit, name: str) -> dict:
    """What one player sees at the trader: the visit, the shared stock with their own limits,
    and their last trades."""
    cfg = service.config()
    service.expire_stale(visit.id)
    stock = service.stock(visit)
    used = service.player_used([s.id for s in stock], name)
    balance = db.scalar(
        select(PlayerStatCache.current_balance).where(
            PlayerStatCache.server_id == server.id,
            PlayerStatCache.minecraft_nickname_normalized == name.strip().lower(),
        )
    )
    recent = db.scalars(
        select(TraderTransaction)
        .where(
            TraderTransaction.visit_id == visit.id,
            TraderTransaction.player_name == name,
        )
        .order_by(TraderTransaction.created_at.desc())
        .limit(10)
    ).all()
    return {
        "visit": {
            "id": str(visit.id),
            "kind": visit.kind,
            "starts_at": _iso(visit.starts_at),
            "ends_at": _iso(visit.ends_at),
        },
        "now": _iso(datetime.now(timezone.utc)),
        "player_share_pct": cfg.player_share_pct,
        "balance": float(balance or 0),
        "stock": [
            {
                "id": str(s.id),
                "side": s.side,
                "slot": s.slot,
                "item_key": s.item_key,
                "display_name": s.display_name,
                "rarity": s.rarity,
                "unit_price": s.unit_price,
                "qty_total": s.qty_total,
                "qty_left": s.qty_left,
                "my_cap": service.player_cap(cfg, s),
                "my_used": used.get(s.id, 0),
            }
            for s in stock
        ],
        "transactions": [_tx_out(tx) for tx in recent],
    }


@ui_router.get("/state")
def state(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    service = TraderService(db, server.id)
    visit = _active_with_session(service, player)
    out = _state(db, server, service, visit, player.minecraft_nickname)
    db.commit()
    return out


class TradeRequest(BaseModel):
    stock_id: UUID
    qty: int = Field(ge=1, le=6400)


@ui_router.post("/trade")
def trade(
    payload: TradeRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    service = TraderService(db, server.id)
    try:
        tx = service.request_trade(player, payload.stock_id, payload.qty)
    except TraderError as exc:
        db.rollback()
        raise _fail(exc)
    db.commit()
    return _tx_out(tx)


@ui_router.get("/transactions/{tx_id}")
def transaction(
    tx_id: UUID,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    tx = db.get(TraderTransaction, tx_id)
    if tx is None or tx.server_id != server.id or tx.player_name.lower() != player.minecraft_nickname.lower():
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    TraderService(db, server.id).expire_stale(tx.visit_id)
    db.commit()
    db.refresh(tx)
    return _tx_out(tx)


# ── game server pages (a plugin draws the trade screen itself, e.g. VoidRP: Origins) ─────────
# Same rules as the WebGUI page: only after right-clicking the NPC (a session from /open), the same
# shared stock and per-player caps. The plugin is the one moving items and money, so the trade is
# not queued as a web action: the plugin settles it at once via /transactions/{id}/result.
class PlayerRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=16)


@plugin_router.post("/player-state")
def player_state(
    payload: PlayerRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    service = TraderService(db, server.id)
    visit = service.active_visit(create=False)
    if visit is None:
        raise HTTPException(status_code=404, detail="Скупщик ушёл. Он регулярно приходит на спавн — следите за уведомлениями.")
    if not service.has_session(payload.player_name, visit):
        raise HTTPException(status_code=403, detail="Торговля открывается только у скупщика: подойдите к нему на спавне и нажмите правой кнопкой.")
    out = _state(db, server, service, visit, payload.player_name)
    db.commit()
    return out


class PlayerTradeRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=16)
    stock_id: UUID
    qty: int = Field(ge=1, le=6400)


@plugin_router.post("/player-trade")
def player_trade(
    payload: PlayerTradeRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Reserves the stock; the plugin moves items and money and reports what went through."""
    service = TraderService(db, server.id)
    user_id = db.scalar(
        select(PlayerAccount.user_id).where(
            PlayerAccount.minecraft_nickname_normalized == payload.player_name.strip().lower()
        )
    )
    try:
        tx = service.reserve(payload.player_name, user_id, payload.stock_id, payload.qty, queue=False)
    except TraderError as exc:
        db.rollback()
        raise _fail(exc)
    db.commit()
    return _tx_out(tx)


def hud_trader_info(db: Session, server_id: UUID) -> dict | None:
    """Short status for the HUD chip: the trader is at spawn, or arrives soon."""
    service = TraderService(db, server_id)
    cfg = service.config()
    if not cfg.enabled:
        return None
    now = datetime.now(timezone.utc)
    visit = service.active_visit(now)
    if visit is not None:
        return {"status": "active", "kind": visit.kind, "ends_at": _iso(visit.ends_at)}
    nxt = service.next_visit_start(now)
    if nxt is not None and (nxt - now).total_seconds() <= cfg.announce_before_minutes * 60:
        return {"status": "soon", "kind": None, "starts_at": _iso(nxt)}
    return None
