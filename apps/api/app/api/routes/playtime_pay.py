"""Pay for playing — the plugin's side (/game-sync/playtime-pay) and the admin panel's
(/admin/salary).

The plugin counts a player's active minutes and, every ``every_minutes`` of them, claims
a payout here. This decides it: nothing while the feature is off, ``amount`` while the
player's total for the day (Moscow time) stays under ``daily_cap``, the rest up to the
cap when it would go over. ``claim_id`` is the plugin's own id for the claim, so a
request retried after a timeout is answered with the payout already made.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.playtime_pay import PlaytimePayout, PlaytimePaySettings, default_playtime_pay
from apps.api.app.models.user import User

MOSCOW = ZoneInfo("Europe/Moscow")

plugin_router = APIRouter(prefix="/game-sync/playtime-pay", tags=["game-sync", "salary"])
admin_router = APIRouter(
    prefix="/admin/salary",
    tags=["admin", "salary"],
    dependencies=[Depends(require_permission("salary.view"))],
)


def today() -> date:
    return datetime.now(MOSCOW).date()


def _row(session: Session, server: GameServer) -> PlaytimePaySettings | None:
    return session.query(PlaytimePaySettings).filter(PlaytimePaySettings.server_id == server.id).one_or_none()


def config_of(session: Session, server: GameServer) -> dict:
    row = _row(session, server)
    return {**default_playtime_pay(), **(row.config if row else {})}


def _paid_today(session: Session, server: GameServer, player_uuid: str, day: date) -> float:
    return float(
        session.query(func.coalesce(func.sum(PlaytimePayout.amount), 0.0))
        .filter(PlaytimePayout.server_id == server.id, PlaytimePayout.day == day,
                PlaytimePayout.player_uuid == player_uuid)
        .scalar()
    )


# ── The plugin ────────────────────────────────────────────────────────────────

@plugin_router.get("/config")
def plugin_config(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    return config_of(session, server)


class ClaimRequest(BaseModel):
    claim_id: str = Field(min_length=8, max_length=64)
    player_uuid: str = Field(min_length=32, max_length=36)
    player_name: str = Field(min_length=1, max_length=64)
    minutes: int = Field(ge=1, le=1440)


@plugin_router.post("/claim")
def claim(
    req: ClaimRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    cfg = config_of(session, server)
    day = today()
    cap = float(cfg["daily_cap"])
    existing = session.query(PlaytimePayout).filter(
        PlaytimePayout.server_id == server.id, PlaytimePayout.claim_id == req.claim_id
    ).one_or_none()
    if existing is not None:
        return {"paid": existing.amount, "paid_today": _paid_today(session, server, req.player_uuid, day),
                "daily_cap": cap, "repeat": True}
    if not cfg["enabled"]:
        return {"paid": 0, "paid_today": 0, "daily_cap": cap, "reason": "off"}
    paid_today = _paid_today(session, server, req.player_uuid, day)
    pay = round(min(float(cfg["amount"]), max(0.0, cap - paid_today)), 2)
    if pay <= 0:
        return {"paid": 0, "paid_today": paid_today, "daily_cap": cap, "reason": "cap"}
    session.add(PlaytimePayout(
        server_id=server.id, claim_id=req.claim_id, player_uuid=req.player_uuid,
        player_name=req.player_name, amount=pay, minutes=req.minutes, day=day,
    ))
    session.commit()
    return {"paid": pay, "paid_today": round(paid_today + pay, 2), "daily_cap": cap}


# ── The admin panel ───────────────────────────────────────────────────────────

@admin_router.get("")
def admin_overview(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    day = today()
    row = _row(session, server)
    base = session.query(PlaytimePayout).filter(PlaytimePayout.server_id == server.id)
    total_today, count_today, players_today = (
        session.query(func.coalesce(func.sum(PlaytimePayout.amount), 0.0), func.count(PlaytimePayout.id),
                      func.count(func.distinct(PlaytimePayout.player_uuid)))
        .filter(PlaytimePayout.server_id == server.id, PlaytimePayout.day == day).one()
    )
    week_from = date.fromordinal(day.toordinal() - 6)
    by_day = (
        session.query(PlaytimePayout.day, func.sum(PlaytimePayout.amount), func.count(func.distinct(PlaytimePayout.player_uuid)))
        .filter(PlaytimePayout.server_id == server.id, PlaytimePayout.day >= week_from)
        .group_by(PlaytimePayout.day).order_by(PlaytimePayout.day).all()
    )
    top = (
        session.query(PlaytimePayout.player_name, func.sum(PlaytimePayout.amount), func.sum(PlaytimePayout.minutes))
        .filter(PlaytimePayout.server_id == server.id, PlaytimePayout.day == day)
        .group_by(PlaytimePayout.player_name).order_by(func.sum(PlaytimePayout.amount).desc()).limit(10).all()
    )
    recent = base.order_by(PlaytimePayout.created_at.desc()).limit(50).all()
    return {
        "settings": config_of(session, server),
        "settings_updated_by": row.updated_by if row else None,
        "today": {"day": day.isoformat(), "total": round(float(total_today), 2), "payouts": count_today, "players": players_today},
        "week": [{"day": d.isoformat(), "total": round(float(t), 2), "players": p} for d, t, p in by_day],
        "top_today": [{"player": n, "total": round(float(t), 2), "minutes": int(m)} for n, t, m in top],
        "recent": [
            {"player": r.player_name, "amount": r.amount, "minutes": r.minutes, "at": r.created_at.isoformat()}
            for r in recent
        ],
    }


class SalarySettings(BaseModel):
    enabled: bool
    amount: float = Field(gt=0, le=1_000_000)
    every_minutes: int = Field(ge=5, le=240)
    daily_cap: float = Field(gt=0, le=100_000_000)
    afk_minutes: int = Field(ge=1, le=60)


@admin_router.put("/settings", dependencies=[Depends(require_permission("salary.manage"))])
def admin_update(
    req: SalarySettings,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    row = _row(session, server)
    config = req.model_dump()
    if row is None:
        row = PlaytimePaySettings(server_id=server.id, config=config)
        session.add(row)
    else:
        row.config = config
    row.updated_by = actor.site_login
    session.commit()
    record_audit(session, actor=actor, category="salary", action="settings", target_type="server",
                 target_id=str(server.id), target_label=server.slug, server_id=server.id, meta=config)
    return {"settings": config, "settings_updated_by": row.updated_by}
