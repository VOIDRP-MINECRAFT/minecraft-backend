from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.punishment import PUNISHMENT_TYPES, Punishment
from apps.api.app.models.user import User

router = APIRouter(
    prefix="/admin/punishments",
    tags=["admin", "punishments"],
    dependencies=[Depends(require_permission("punishments.view"))],
)


def _fmt_duration(seconds: int) -> str:
    """Seconds → EssentialsX duration string (e.g. 90000 → '1d1h')."""
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s and not parts:
        parts.append(f"{s}s")
    return "".join(parts) or "1m"


def _enforce_rcon(server: GameServer, p: Punishment) -> str | None:
    """Dispatch the in-game command for a punishment. Best-effort; returns an
    error string on failure (so the row is still saved), else None."""
    name = p.player_name
    reason = p.reason or "Нарушение правил"
    if p.type == "ban":
        cmd = f"ban {name} {reason}"
    elif p.type == "tempban":
        dur = _fmt_duration(int((p.expires_at - datetime.now(timezone.utc)).total_seconds())) if p.expires_at else "1d"
        cmd = f"tempban {name} {dur} {reason}"
    elif p.type == "mute":
        cmd = f"mute {name}"
    elif p.type == "tempmute":
        dur = _fmt_duration(int((p.expires_at - datetime.now(timezone.utc)).total_seconds())) if p.expires_at else "1h"
        cmd = f"mute {name} {dur}"
    elif p.type == "kick":
        cmd = f"kick {name} {reason}"
    else:  # warn — nothing to enforce in-game
        return None
    try:
        server_ops.rcon_command(server, cmd)
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def _revoke_rcon(server: GameServer, p: Punishment) -> str | None:
    if p.type in ("ban", "tempban"):
        cmd = f"unban {p.player_name}"
    elif p.type in ("mute", "tempmute"):
        cmd = f"unmute {p.player_name}"
    else:
        return None
    try:
        server_ops.rcon_command(server, cmd)
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def _serialize(p: Punishment) -> dict:
    return {
        "id": str(p.id),
        "server_id": str(p.server_id) if p.server_id else None,
        "player_uuid": p.player_uuid,
        "player_name": p.player_name,
        "type": p.type,
        "reason": p.reason,
        "issued_by_name": p.issued_by_name,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "active": p.active,
        "effective": p.is_effective,
        "expired": p.is_expired,
        "revoked_at": p.revoked_at.isoformat() if p.revoked_at else None,
        "revoked_by_name": p.revoked_by_name,
        "revoke_reason": p.revoke_reason,
        "created_at": p.created_at.isoformat(),
    }


@router.get("")
def list_punishments(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    q: Annotated[str | None, Query(max_length=64)] = None,
    type: Annotated[str | None, Query(max_length=16)] = None,
    status: Annotated[str, Query(pattern=r"^(active|all)$")] = "active",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Punishments for the active server plus platform-wide ones, newest first.
    ``status=active`` shows only standing (unrevoked, unexpired) bans/mutes."""
    conds = [or_(Punishment.server_id == server.id, Punishment.server_id.is_(None))]
    if type:
        conds.append(Punishment.type == type)
    if q:
        conds.append(Punishment.player_name.ilike(f"%{q.strip()}%"))
    if status == "active":
        conds.append(Punishment.active.is_(True))
        conds.append(
            or_(Punishment.expires_at.is_(None), Punishment.expires_at > datetime.now(timezone.utc))
        )

    total = session.scalar(select(func.count()).select_from(Punishment).where(*conds)) or 0
    rows = session.scalars(
        select(Punishment).where(*conds).order_by(Punishment.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return {"items": [_serialize(p) for p in rows], "total": total}


class PunishmentCreate(BaseModel):
    player: str = Field(min_length=1, max_length=64)
    uuid: str | None = Field(default=None, max_length=36)
    type: str
    reason: str | None = Field(default=None, max_length=500)
    duration_seconds: int | None = Field(default=None, ge=0)
    scope: str = Field(default="server")  # server | global
    enforce: bool = True


@router.post("", dependencies=[Depends(require_permission("punishments.manage"))])
def create_punishment(
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
    payload: Annotated[PunishmentCreate, Body(...)],
) -> dict:
    if payload.type not in PUNISHMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown punishment type: {payload.type}")

    expires_at = None
    if payload.type in ("tempban", "tempmute"):
        if not payload.duration_seconds:
            raise HTTPException(status_code=400, detail="Временное наказание требует срок")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.duration_seconds)

    # ``active`` = record is live / not revoked (true for every type on issue).
    # Whether a punishment is currently *in force* (a standing ban/mute that
    # hasn't expired) is computed separately via ``is_effective`` — so kick/warn
    # are still recorded and visible in the list, just badged "Разово" rather
    # than "Действует".
    p = Punishment(
        server_id=None if payload.scope == "global" else server.id,
        player_uuid=payload.uuid,
        player_name=payload.player.strip(),
        type=payload.type,
        reason=(payload.reason or None),
        issued_by_user_id=actor.id,
        issued_by_name=actor.site_login,
        expires_at=expires_at,
        active=True,
    )
    session.add(p)
    session.flush()

    enforce_err = _enforce_rcon(server, p) if payload.enforce else None
    session.commit()
    session.refresh(p)

    record_audit(
        session,
        actor=actor,
        category="punishment",
        action=f"issue_{payload.type}",
        target_type="player",
        target_id=payload.uuid or payload.player,
        target_label=payload.player,
        server_id=p.server_id,
        meta={"reason": payload.reason, "duration_seconds": payload.duration_seconds,
              "scope": payload.scope, "enforced": payload.enforce, "rcon_error": enforce_err},
    )

    return {"punishment": _serialize(p), "enforced": payload.enforce, "rcon_error": enforce_err}


class PunishmentRevoke(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    lift_in_game: bool = True


@router.post("/{punishment_id}/revoke", dependencies=[Depends(require_permission("punishments.manage"))])
def revoke_punishment(
    punishment_id: str,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
    payload: Annotated[PunishmentRevoke, Body()] = PunishmentRevoke(),
) -> dict:
    p = session.get(Punishment, punishment_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Наказание не найдено")
    if not p.active:
        raise HTTPException(status_code=409, detail="Наказание уже снято")

    p.active = False
    p.revoked_at = datetime.now(timezone.utc)
    p.revoked_by_name = actor.site_login
    p.revoke_reason = payload.reason or None

    lift_err = _revoke_rcon(server, p) if payload.lift_in_game else None
    session.commit()
    session.refresh(p)

    record_audit(
        session,
        actor=actor,
        category="punishment",
        action=f"revoke_{p.type}",
        target_type="player",
        target_id=p.player_uuid or p.player_name,
        target_label=p.player_name,
        server_id=p.server_id,
        meta={"reason": payload.reason, "rcon_error": lift_err},
    )
    return {"punishment": _serialize(p), "rcon_error": lift_err}
