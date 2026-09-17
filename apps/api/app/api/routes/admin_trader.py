"""Admin panel for the travelling trader (per server): status, settings, catalog, visits, trades."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.trader import (
    TraderCatalogItem,
    TraderStock,
    TraderTransaction,
    TraderVisit,
)
from apps.api.app.models.user import User
from apps.api.app.services.trader_service import PHASES, TraderConfig, TraderError, TraderService

router = APIRouter(
    prefix="/admin/trader",
    tags=["admin", "trader"],
    dependencies=[Depends(require_permission("trader.view"))],
)
_MANAGE = Depends(require_permission("trader.manage"))


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _visit_out(v: TraderVisit) -> dict:
    return {
        "id": str(v.id),
        "kind": v.kind,
        "starts_at": _iso(v.starts_at),
        "ends_at": _iso(v.ends_at),
        "phases": v.phases.split(",") if v.phases else [],
        "payout_budget": v.payout_budget,
        "source": v.source,
        "created_by": v.created_by,
    }


def _visit_totals(db: Session, visit_ids: list[UUID]) -> dict[UUID, dict]:
    if not visit_ids:
        return {}
    rows = db.execute(
        select(
            TraderTransaction.visit_id,
            func.sum(case((TraderTransaction.side == "buy", TraderTransaction.total), else_=0)),
            func.sum(case((TraderTransaction.side == "sell", TraderTransaction.total), else_=0)),
            func.count(func.distinct(TraderTransaction.player_name)),
            func.count(TraderTransaction.id),
        )
        .where(TraderTransaction.visit_id.in_(visit_ids), TraderTransaction.status == "done")
        .group_by(TraderTransaction.visit_id)
    ).all()
    return {
        vid: {"paid_out": round(float(p or 0), 2), "earned": round(float(e or 0), 2), "players": int(n or 0), "trades": int(c or 0)}
        for vid, p, e, n, c in rows
    }


# ── status & settings ────────────────────────────────────────────────────────
@router.get("/status")
def status(
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    service = TraderService(db, server.id)
    cfg = service.config()
    row = service.settings_row()
    count, avg = service.bp_activity(cfg)
    active = service.active_visit(create=False)
    next_start = service.next_visit_start()
    catalog = db.execute(
        select(TraderCatalogItem.phase, TraderCatalogItem.rarity, func.count(TraderCatalogItem.id))
        .where(TraderCatalogItem.server_id == server.id, TraderCatalogItem.enabled.is_(True))
        .group_by(TraderCatalogItem.phase, TraderCatalogItem.rarity)
    ).all()
    active_out = None
    if active is not None:
        stock = service.stock(active)
        active_out = {
            **_visit_out(active),
            **_visit_totals(db, [active.id]).get(active.id, {"paid_out": 0, "earned": 0, "players": 0, "trades": 0}),
            "stock_value_buy": round(sum(s.qty_total * s.unit_price for s in stock if s.side == "buy"), 2),
            "slots": len(stock),
        }
    db.commit()
    return {
        "config": cfg.model_dump(),
        "phases": {
            "mid_unlocked_at": _iso(row.mid_unlocked_at),
            "end_unlocked_at": _iso(row.end_unlocked_at),
            "active_players": count,
            "avg_bp_level": round(avg, 1),
        },
        "active": active_out,
        "next_start": _iso(next_start),
        "catalog": [{"phase": p, "rarity": r, "count": c} for p, r, c in catalog],
        "updated_by": row.updated_by,
        "updated_at": _iso(row.updated_at),
    }


class PhaseOverride(BaseModel):
    mid_unlocked: bool | None = None
    end_unlocked: bool | None = None


class SettingsRequest(BaseModel):
    config: dict
    phases: PhaseOverride | None = None


@router.put("/settings", dependencies=[_MANAGE])
def save_settings(
    payload: SettingsRequest,
    request: Request,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    try:
        cfg = TraderConfig.model_validate(payload.config)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(x) for x in first.get("loc", []))
        raise HTTPException(status_code=422, detail=f"{field}: {first.get('msg')}")
    service = TraderService(db, server.id)
    row = service.save_config(cfg, admin.site_login)
    now = datetime.now(timezone.utc)
    if payload.phases is not None:
        if payload.phases.mid_unlocked is not None:
            row.mid_unlocked_at = (row.mid_unlocked_at or now) if payload.phases.mid_unlocked else None
        if payload.phases.end_unlocked is not None:
            row.end_unlocked_at = (row.end_unlocked_at or now) if payload.phases.end_unlocked else None
    record_audit(db, category="trader", action="settings", actor=admin, server_id=server.id,
                 meta={"enabled": cfg.enabled, "budget": cfg.payout_budget}, request=request, commit=False)
    db.commit()
    return {"ok": True}


# ── catalog ──────────────────────────────────────────────────────────────────
class CatalogIn(BaseModel):
    item_key: str = Field(min_length=3, max_length=128, pattern=r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    rarity: int = Field(ge=1, le=3)
    phase: str
    unit_value: float = Field(gt=0, le=1e9)
    can_buy: bool = True
    can_sell: bool = True
    qty_min: int | None = Field(default=None, ge=1, le=6400)
    qty_max: int | None = Field(default=None, ge=1, le=6400)
    enabled: bool = True
    note: str | None = Field(default=None, max_length=256)

    @field_validator("phase")
    @classmethod
    def _phase(cls, v: str) -> str:
        if v not in PHASES:
            raise ValueError("phase: early | mid | end")
        return v


class CatalogPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    rarity: int | None = Field(default=None, ge=1, le=3)
    phase: str | None = None
    unit_value: float | None = Field(default=None, gt=0, le=1e9)
    can_buy: bool | None = None
    can_sell: bool | None = None
    qty_min: int | None = Field(default=None, ge=1, le=6400)
    qty_max: int | None = Field(default=None, ge=1, le=6400)
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=256)

    @field_validator("phase")
    @classmethod
    def _phase(cls, v: str | None) -> str | None:
        if v is not None and v not in PHASES:
            raise ValueError("phase: early | mid | end")
        return v


def _catalog_out(c: TraderCatalogItem) -> dict:
    return {
        "id": str(c.id),
        "item_key": c.item_key,
        "display_name": c.display_name,
        "rarity": c.rarity,
        "phase": c.phase,
        "unit_value": c.unit_value,
        "can_buy": c.can_buy,
        "can_sell": c.can_sell,
        "qty_min": c.qty_min,
        "qty_max": c.qty_max,
        "enabled": c.enabled,
        "note": c.note,
    }


@router.get("/catalog")
def list_catalog(
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
    q: str | None = Query(default=None, max_length=64),
    rarity: int | None = Query(default=None, ge=1, le=3),
    phase: str | None = None,
    enabled: bool | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> dict:
    stmt = select(TraderCatalogItem).where(TraderCatalogItem.server_id == server.id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(TraderCatalogItem.item_key).like(like), func.lower(TraderCatalogItem.display_name).like(like)))
    if rarity:
        stmt = stmt.where(TraderCatalogItem.rarity == rarity)
    if phase in PHASES:
        stmt = stmt.where(TraderCatalogItem.phase == phase)
    if enabled is not None:
        stmt = stmt.where(TraderCatalogItem.enabled.is_(enabled))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(TraderCatalogItem.rarity, TraderCatalogItem.phase, TraderCatalogItem.display_name)
        .offset((page - 1) * per_page).limit(per_page)
    ).all()
    return {"items": [_catalog_out(c) for c in rows], "total": int(total or 0), "page": page, "per_page": per_page}


def _check_qty(qty_min: int | None, qty_max: int | None) -> None:
    if (qty_min is None) != (qty_max is None):
        raise HTTPException(status_code=422, detail="Укажите оба значения количества или ни одного")
    if qty_min is not None and qty_max < qty_min:
        raise HTTPException(status_code=422, detail="Максимальное количество меньше минимального")


@router.post("/catalog", dependencies=[_MANAGE])
def create_catalog(
    payload: CatalogIn,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    _check_qty(payload.qty_min, payload.qty_max)
    row = TraderCatalogItem(server_id=server.id, **payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот предмет уже есть в каталоге")
    return _catalog_out(row)


@router.patch("/catalog/{item_id}", dependencies=[_MANAGE])
def update_catalog(
    item_id: UUID,
    payload: CatalogPatch,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    row = db.get(TraderCatalogItem, item_id)
    if row is None or row.server_id != server.id:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key in ("display_name", "rarity", "phase", "unit_value", "can_buy", "can_sell", "enabled") and value is None:
            continue
        setattr(row, key, value)
    _check_qty(row.qty_min, row.qty_max)
    db.commit()
    return _catalog_out(row)


class BulkRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=1000)
    enabled: bool | None = None
    phase: str | None = None
    rarity: int | None = Field(default=None, ge=1, le=3)
    value_mult: float | None = Field(default=None, gt=0, le=100)


@router.post("/catalog/bulk", dependencies=[_MANAGE])
def bulk_catalog(
    payload: BulkRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    if payload.phase is not None and payload.phase not in PHASES:
        raise HTTPException(status_code=422, detail="phase: early | mid | end")
    rows = db.scalars(
        select(TraderCatalogItem).where(TraderCatalogItem.server_id == server.id, TraderCatalogItem.id.in_(payload.ids))
    ).all()
    for row in rows:
        if payload.enabled is not None:
            row.enabled = payload.enabled
        if payload.phase is not None:
            row.phase = payload.phase
        if payload.rarity is not None:
            row.rarity = payload.rarity
        if payload.value_mult is not None:
            row.unit_value = round(row.unit_value * payload.value_mult, 2)
    db.commit()
    return {"updated": len(rows)}


@router.delete("/catalog/{item_id}", dependencies=[_MANAGE])
def delete_catalog(
    item_id: UUID,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    row = db.get(TraderCatalogItem, item_id)
    if row is None or row.server_id != server.id:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── visits ───────────────────────────────────────────────────────────────────
class ForceRequest(BaseModel):
    kind: str = "normal"


@router.post("/visits/force", dependencies=[_MANAGE])
def force_visit(
    payload: ForceRequest,
    request: Request,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    service = TraderService(db, server.id)
    try:
        visit = service.force_visit(payload.kind, admin.site_login)
    except TraderError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc))
    record_audit(db, category="trader", action="force_visit", actor=admin, server_id=server.id,
                 target_type="trader_visit", target_id=str(visit.id), meta={"kind": visit.kind}, request=request, commit=False)
    db.commit()
    return _visit_out(visit)


@router.post("/visits/{visit_id}/end", dependencies=[_MANAGE])
def end_visit(
    visit_id: UUID,
    request: Request,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    service = TraderService(db, server.id)
    try:
        visit = service.end_visit(visit_id)
    except TraderError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    record_audit(db, category="trader", action="end_visit", actor=admin, server_id=server.id,
                 target_type="trader_visit", target_id=str(visit.id), request=request, commit=False)
    db.commit()
    return _visit_out(visit)


class PreviewRequest(BaseModel):
    kind: str = "normal"


@router.post("/preview")
def preview_roll(
    payload: PreviewRequest,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Roll a visit without saving it — to check how the catalog and weights play out."""
    import random

    service = TraderService(db, server.id)
    cfg = service.config()
    kind = payload.kind if payload.kind in ("normal", "weekend", "elite") else "normal"
    budget = cfg.payout_budget * (cfg.elite_budget_mult if kind == "elite" else cfg.weekend_budget_mult if kind == "weekend" else 1.0)
    row = service.settings_row()
    phases = ["early"] + (["mid"] if row.mid_unlocked_at else []) + (["end"] if row.end_unlocked_at else [])
    rolled = service.roll(cfg, kind, phases, random.SystemRandom().getrandbits(62), budget)
    db.rollback()
    return {
        "kind": kind,
        "phases": phases,
        "payout_budget": round(budget, 2),
        "slots": [
            {
                "side": s.side, "slot": s.slot, "item_key": s.item.item_key, "display_name": s.item.display_name,
                "rarity": s.rarity, "qty": s.qty, "unit_price": s.unit_price, "value": round(s.qty * s.unit_price, 2),
            }
            for s in rolled
        ],
    }


@router.get("/visits")
def list_visits(
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict:
    base = select(TraderVisit).where(
        TraderVisit.server_id == server.id,
        TraderVisit.starts_at <= datetime.now(timezone.utc) + timedelta(hours=1),
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(TraderVisit.starts_at.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    totals = _visit_totals(db, [v.id for v in rows])
    empty = {"paid_out": 0, "earned": 0, "players": 0, "trades": 0}
    return {
        "items": [{**_visit_out(v), **totals.get(v.id, empty)} for v in rows],
        "total": int(total or 0),
        "page": page,
        "per_page": per_page,
    }


@router.get("/visits/{visit_id}")
def visit_detail(
    visit_id: UUID,
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    visit = db.get(TraderVisit, visit_id)
    if visit is None or visit.server_id != server.id:
        raise HTTPException(status_code=404, detail="Визит не найден")
    stock = db.scalars(select(TraderStock).where(TraderStock.visit_id == visit.id).order_by(TraderStock.side, TraderStock.slot)).all()
    return {
        **_visit_out(visit),
        **_visit_totals(db, [visit.id]).get(visit.id, {"paid_out": 0, "earned": 0, "players": 0, "trades": 0}),
        "stock": [
            {
                "id": str(s.id), "side": s.side, "slot": s.slot, "item_key": s.item_key, "display_name": s.display_name,
                "rarity": s.rarity, "unit_price": s.unit_price, "qty_total": s.qty_total, "qty_left": s.qty_left,
            }
            for s in stock
        ],
    }


@router.get("/transactions")
def list_transactions(
    server: Annotated[GameServer, Depends(resolve_server)],
    db: Annotated[Session, Depends(get_db_session)],
    visit_id: UUID | None = None,
    player: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> dict:
    stmt = select(TraderTransaction).where(TraderTransaction.server_id == server.id)
    if visit_id:
        stmt = stmt.where(TraderTransaction.visit_id == visit_id)
    if player:
        stmt = stmt.where(func.lower(TraderTransaction.player_name).like(f"%{player.lower()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(TraderTransaction.created_at.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return {
        "items": [
            {
                "id": str(t.id), "visit_id": str(t.visit_id), "player_name": t.player_name, "side": t.side,
                "item_key": t.item_key, "qty_requested": t.qty_requested, "qty_done": t.qty_done,
                "unit_price": t.unit_price, "total": t.total, "status": t.status, "error": t.error,
                "created_at": _iso(t.created_at), "completed_at": _iso(t.completed_at),
            }
            for t in rows
        ],
        "total": int(total or 0),
        "page": page,
        "per_page": per_page,
    }
