from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from apps.api.app.core import server_ops
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.anticheat import (
    AnticheatAction,
    AnticheatInjectionReport,
    AnticheatModSnapshot,
    AnticheatThresholdConfig,
    AnticheatViolation,
    ModVerdict,
)
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user import User

router = APIRouter(
    prefix="/admin/anticheat",
    tags=["admin", "anticheat"],
    dependencies=[Depends(require_permission("anticheat.view"))],
)


# ── Response schemas ─────────────────────────────────────────────────────────

class AnticheatPlayerSummary(BaseModel):
    player_uuid: str
    player_nick: str
    total_violations: int
    high_count: int
    medium_count: int
    low_count: int
    unreviewed_count: int
    last_violation_at: str | None
    has_suspicious_mods: bool
    suspicious_mod_names: list[str]

    model_config = {"from_attributes": True}


class AnticheatPlayerListResponse(BaseModel):
    items: list[AnticheatPlayerSummary]
    total: int


class ViolationDetail(BaseModel):
    id: str
    check_type: str
    details: str
    actual_value: float
    expected_max: float
    vl: int
    severity: str
    reviewed: bool
    review_action: str | None
    reviewed_by: str | None
    created_at: str

    model_config = {"from_attributes": True}


class ModSnapshotDetail(BaseModel):
    id: str
    mods: list[str]
    suspicious_mods: list[str]
    is_verified: bool
    resource_pack_status: str
    created_at: str

    model_config = {"from_attributes": True}


class InjectionReportDetail(BaseModel):
    id: str
    java_agents: list[str]
    suspicious_libraries: list[str]
    agents_detected: bool
    created_at: str


class AnticheatPlayerDetail(BaseModel):
    player_uuid: str
    player_nick: str
    violations: list[ViolationDetail]
    snapshots: list[ModSnapshotDetail]
    injection_reports: list[InjectionReportDetail]
    account_active: bool | None


class ModVerdictOut(BaseModel):
    id: str
    mod_id: str
    verdict: str
    reviewed_by: str | None
    notes: str | None
    created_at: str


class SetModVerdictRequest(BaseModel):
    mod_id: str
    verdict: str        # CHEAT | SAFE
    reviewed_by: str = "admin"
    notes: str = ""


class ActionRequest(BaseModel):
    action: str  # kick | disable | enable | clear_violations
    reason: str = ""
    reviewed_by: str = "admin"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _latest_suspicious(session: Session, player_uuid: str, server_id) -> list[str]:
    snap = (
        session.query(AnticheatModSnapshot)
        .filter(
            AnticheatModSnapshot.player_uuid == player_uuid,
            AnticheatModSnapshot.server_id == server_id,
        )
        .order_by(AnticheatModSnapshot.created_at.desc())
        .first()
    )
    if snap is None:
        return []
    try:
        return json.loads(snap.suspicious_mods) or []
    except Exception:
        return []


def _find_user(session: Session, nick: str) -> User | None:
    pa = (
        session.query(PlayerAccount)
        .filter(PlayerAccount.minecraft_nickname_normalized == nick.lower())
        .first()
    )
    if pa is None:
        return None
    return session.query(User).filter(User.id == pa.user_id).first()


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/players", response_model=AnticheatPlayerListResponse)
def list_players(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    only_suspicious: bool = Query(default=False),
) -> AnticheatPlayerListResponse:
    q = (
        session.query(
            AnticheatViolation.player_uuid,
            AnticheatViolation.player_nick,
            func.count(AnticheatViolation.id).label("total"),
            func.sum(case((AnticheatViolation.severity == "HIGH", 1), else_=0)).label("high"),
            func.sum(case((AnticheatViolation.severity == "MEDIUM", 1), else_=0)).label("medium"),
            func.sum(case((AnticheatViolation.severity == "LOW", 1), else_=0)).label("low"),
            func.sum(case((AnticheatViolation.reviewed == False, 1), else_=0)).label("unreviewed"),  # noqa: E712
            func.max(AnticheatViolation.created_at).label("last_at"),
        )
        .filter(AnticheatViolation.server_id == server.id)
        .group_by(AnticheatViolation.player_uuid, AnticheatViolation.player_nick)
        .order_by(func.max(AnticheatViolation.created_at).desc())
    )
    total = q.count()
    rows = q.offset(skip).limit(limit).all()

    items: list[AnticheatPlayerSummary] = []
    for row in rows:
        suspicious = _latest_suspicious(session, row.player_uuid, server.id)
        if only_suspicious and not suspicious:
            continue
        items.append(AnticheatPlayerSummary(
            player_uuid=row.player_uuid,
            player_nick=row.player_nick,
            total_violations=row.total or 0,
            high_count=row.high or 0,
            medium_count=row.medium or 0,
            low_count=row.low or 0,
            unreviewed_count=row.unreviewed or 0,
            last_violation_at=row.last_at.isoformat() if row.last_at else None,
            has_suspicious_mods=bool(suspicious),
            suspicious_mod_names=suspicious,
        ))

    return AnticheatPlayerListResponse(items=items, total=total)


@router.get("/player/{player_uuid}", response_model=AnticheatPlayerDetail)
def get_player_detail(
    player_uuid: str,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> AnticheatPlayerDetail:
    violations = (
        session.query(AnticheatViolation)
        .filter(
            AnticheatViolation.player_uuid == player_uuid,
            AnticheatViolation.server_id == server.id,
        )
        .order_by(AnticheatViolation.created_at.desc())
        .all()
    )
    snapshots = (
        session.query(AnticheatModSnapshot)
        .filter(
            AnticheatModSnapshot.player_uuid == player_uuid,
            AnticheatModSnapshot.server_id == server.id,
        )
        .order_by(AnticheatModSnapshot.created_at.desc())
        .all()
    )
    if not violations and not snapshots:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    nick = violations[0].player_nick if violations else snapshots[0].player_nick
    user = _find_user(session, nick)

    violation_details = [
        ViolationDetail(
            id=str(v.id),
            check_type=v.check_type,
            details=v.details,
            actual_value=v.actual_value,
            expected_max=v.expected_max,
            vl=v.vl,
            severity=v.severity,
            reviewed=v.reviewed,
            review_action=v.review_action,
            reviewed_by=v.reviewed_by,
            created_at=v.created_at.isoformat(),
        )
        for v in violations
    ]
    snapshot_details = [
        ModSnapshotDetail(
            id=str(s.id),
            mods=_parse_json_list(s.mods),
            suspicious_mods=_parse_json_list(s.suspicious_mods),
            is_verified=s.is_verified,
            resource_pack_status=s.resource_pack_status,
            created_at=s.created_at.isoformat(),
        )
        for s in snapshots
    ]

    injection_records = (
        session.query(AnticheatInjectionReport)
        .filter(
            AnticheatInjectionReport.player_uuid == player_uuid,
            AnticheatInjectionReport.server_id == server.id,
        )
        .order_by(AnticheatInjectionReport.created_at.desc())
        .all()
    )
    injection_details = [
        InjectionReportDetail(
            id=str(r.id),
            java_agents=_parse_json_list(r.java_agents),
            suspicious_libraries=_parse_json_list(r.suspicious_libraries),
            agents_detected=r.agents_detected,
            created_at=r.created_at.isoformat(),
        )
        for r in injection_records
    ]

    return AnticheatPlayerDetail(
        player_uuid=player_uuid,
        player_nick=nick,
        violations=violation_details,
        snapshots=snapshot_details,
        injection_reports=injection_details,
        account_active=user.is_active if user else None,
    )


@router.post("/player/{player_uuid}/action", dependencies=[Depends(require_permission("anticheat.manage"))])
def player_action(
    player_uuid: str,
    req: ActionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> dict[str, str]:
    violations = (
        session.query(AnticheatViolation)
        .filter(
            AnticheatViolation.player_uuid == player_uuid,
            AnticheatViolation.server_id == server.id,
        )
        .all()
    )
    snapshots = (
        session.query(AnticheatModSnapshot)
        .filter(
            AnticheatModSnapshot.player_uuid == player_uuid,
            AnticheatModSnapshot.server_id == server.id,
        )
        .all()
    )
    if not violations and not snapshots:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    nick = violations[0].player_nick if violations else snapshots[0].player_nick
    reason = req.reason or "Действие администратора"
    rcon_error: str | None = None

    def rcon(command: str) -> None:
        # The server chosen in the admin panel, not the main one: each has its own RCON.
        nonlocal rcon_error
        try:
            server_ops.rcon_command(server, command)
        except Exception as exc:  # noqa: BLE001 — best effort, the action itself stands
            rcon_error = str(exc)

    if req.action == "kick":
        rcon(f"kick {nick} {reason}")

    elif req.action in ("disable", "enable"):
        user = _find_user(session, nick)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site account not found")
        user.is_active = req.action == "enable"
        session.commit()
        if req.action == "disable":
            rcon(f"kick {nick} Аккаунт заблокирован")

    elif req.action == "clear_violations":
        for v in violations:
            v.reviewed = True
            v.review_action = "cleared"
            v.reviewed_by = req.reviewed_by
        session.commit()

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {req.action}")

    record_audit(session, actor=actor, category="anticheat", action=req.action,
                 target_type="player", target_id=player_uuid, target_label=nick,
                 server_id=server.id, meta={"reason": req.reason, "rcon_error": rcon_error})
    result = {"ok": "true", "action": req.action, "nick": nick}
    if rcon_error:
        result["rcon_error"] = rcon_error
    return result


class DeletePlayersRequest(BaseModel):
    player_uuids: list[str]


@router.post("/players/delete", dependencies=[Depends(require_permission("anticheat.manage"))])
def delete_players(
    req: DeletePlayersRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict[str, int]:
    """Permanently remove all anticheat records (violations, mod snapshots,
    injection reports) for the given players on the current server. This is what
    drops them off the players list — ``clear_violations`` only marks them
    reviewed. Scoped to ``server.id`` so it never touches other servers' data."""
    uuids = [u for u in dict.fromkeys(req.player_uuids) if u]  # dedupe, drop blanks
    if not uuids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No players specified")

    violations = (
        session.query(AnticheatViolation)
        .filter(AnticheatViolation.server_id == server.id, AnticheatViolation.player_uuid.in_(uuids))
        .delete(synchronize_session=False)
    )
    snapshots = (
        session.query(AnticheatModSnapshot)
        .filter(AnticheatModSnapshot.server_id == server.id, AnticheatModSnapshot.player_uuid.in_(uuids))
        .delete(synchronize_session=False)
    )
    injections = (
        session.query(AnticheatInjectionReport)
        .filter(AnticheatInjectionReport.server_id == server.id, AnticheatInjectionReport.player_uuid.in_(uuids))
        .delete(synchronize_session=False)
    )
    session.commit()
    return {
        "players": len(uuids),
        "violations": violations,
        "snapshots": snapshots,
        "injection_reports": injections,
    }


def _parse_json_list(text: str) -> list[str]:
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except Exception:
        return []


# ── Mod verdict endpoints ─────────────────────────────────────────────────────

@router.get("/mod-verdicts", response_model=list[ModVerdictOut])
def list_mod_verdicts(
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ModVerdictOut]:
    rows = session.query(ModVerdict).order_by(ModVerdict.created_at.desc()).all()
    return [
        ModVerdictOut(
            id=str(r.id),
            mod_id=r.mod_id,
            verdict=r.verdict,
            reviewed_by=r.reviewed_by,
            notes=r.notes,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.post("/mod-verdicts", response_model=ModVerdictOut, status_code=200, dependencies=[Depends(require_permission("anticheat.manage"))])
def set_mod_verdict(
    req: SetModVerdictRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> ModVerdictOut:
    if req.verdict not in ("CHEAT", "SAFE"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="verdict must be CHEAT or SAFE")
    existing = session.query(ModVerdict).filter(ModVerdict.mod_id == req.mod_id.lower()).first()
    if existing:
        existing.verdict = req.verdict
        existing.reviewed_by = req.reviewed_by or None
        existing.notes = req.notes or None
        session.commit()
        session.refresh(existing)
        row = existing
    else:
        from uuid import uuid4
        row = ModVerdict(
            id=str(uuid4()),
            mod_id=req.mod_id.lower(),
            verdict=req.verdict,
            reviewed_by=req.reviewed_by or None,
            notes=req.notes or None,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return ModVerdictOut(
        id=str(row.id),
        mod_id=row.mod_id,
        verdict=row.verdict,
        reviewed_by=row.reviewed_by,
        notes=row.notes,
        created_at=row.created_at.isoformat(),
    )


@router.delete("/mod-verdicts/{mod_id}", status_code=204, dependencies=[Depends(require_permission("anticheat.manage"))])
def delete_mod_verdict(
    mod_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    row = session.query(ModVerdict).filter(ModVerdict.mod_id == mod_id.lower()).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verdict not found")
    session.delete(row)
    session.commit()


# ── Threshold config ──────────────────────────────────────────────────────────

_DEFAULT_CONFIGS = [
    # NeoForge mod (voidrp_anticheat)
    {"key": "vl_threshold", "value": 10.0, "label": "Порог VL", "description": "Сколько VL нужно для репорта нарушения", "min_value": 1.0, "max_value": 100.0, "step": 1.0},
    {"key": "speed_threshold", "value": 0.75, "label": "Скорость (блоков/тик)", "description": "Максимальная горизонтальная скорость без эффектов", "min_value": 0.3, "max_value": 5.0, "step": 0.05},
    {"key": "fly_ticks_threshold", "value": 40.0, "label": "Полёт (тиков)", "description": "Тиков в воздухе без снижения до флага", "min_value": 5.0, "max_value": 200.0, "step": 1.0},
    {"key": "reach_threshold", "value": 6.5, "label": "Дальность удара (блоков)", "description": "Максимальная дистанция атаки", "min_value": 3.0, "max_value": 20.0, "step": 0.5},
    {"key": "killaura_targets_per_second", "value": 6.0, "label": "KillAura: целей в сек", "description": "Максимум разных целей за 1 секунду", "min_value": 2.0, "max_value": 20.0, "step": 1.0},
    {"key": "cps_threshold", "value": 25.0, "label": "Порог CPS", "description": "Максимум кликов в секунду", "min_value": 10.0, "max_value": 50.0, "step": 1.0},
    # Paper plugin (voidrp_guard)
    {"key": "guard_grim_min_vl", "value": 5.0, "label": "Grim: VL до записи", "description": "С какого VL флаг GrimAC попадает в админку (ниже — только копится)", "min_value": 1.0, "max_value": 100.0, "step": 1.0},
    {"key": "guard_report_cooldown", "value": 10.0, "label": "Интервал записей (сек)", "description": "Не чаще одной записи на игрока и проверку за столько секунд", "min_value": 1.0, "max_value": 300.0, "step": 1.0},
    {"key": "guard_xray_min_stone", "value": 300.0, "label": "Иксрей: вскопано камня", "description": "Сколько камня игрок должен вскопать, прежде чем считать долю руды", "min_value": 50.0, "max_value": 5000.0, "step": 50.0},
    {"key": "guard_xray_ratio", "value": 2.0, "label": "Иксрей: жил на 100 камня", "description": "Жил алмазов, изумрудов и древних обломков на 100 вскопанного камня; выше — подозрение (честная ветка — обычно меньше 1)", "min_value": 0.5, "max_value": 20.0, "step": 0.5},
    {"key": "guard_grief_blocks", "value": 25.0, "label": "Гриф: чужих блоков", "description": "Сколько чужих блоков сломать за окно, чтобы попасть в админку", "min_value": 5.0, "max_value": 500.0, "step": 5.0},
    {"key": "guard_grief_containers", "value": 4.0, "label": "Гриф: чужих сундуков", "description": "Сколько чужих сундуков открыть или опустошить за окно", "min_value": 1.0, "max_value": 50.0, "step": 1.0},
    {"key": "guard_grief_window", "value": 300.0, "label": "Гриф: окно (сек)", "description": "За какое время считаются чужие блоки и сундуки", "min_value": 30.0, "max_value": 3600.0, "step": 30.0},
    {"key": "guard_grief_owner_days", "value": 14.0, "label": "Гриф: давность постройки (дней)", "description": "Блоки, поставленные другим игроком не раньше стольких дней назад, считаются чужими", "min_value": 1.0, "max_value": 90.0, "step": 1.0},
]


def _ensure_defaults(session: Session) -> None:
    """Rows without a server are the defaults every server starts from."""
    existing = {
        r.key for r in session.query(AnticheatThresholdConfig)
        .filter(AnticheatThresholdConfig.server_id.is_(None)).all()
    }
    for cfg in _DEFAULT_CONFIGS:
        if cfg["key"] not in existing:
            session.add(AnticheatThresholdConfig(server_id=None, **cfg))
    session.commit()


class ThresholdConfigOut(BaseModel):
    key: str
    value: float
    label: str
    description: str
    min_value: float
    max_value: float
    step: float
    updated_by: str | None
    updated_at: str
    # The value every server gets, and whether this server has its own instead.
    default_value: float
    overridden: bool


class ThresholdUpdateItem(BaseModel):
    key: str
    value: float


class ThresholdUpdateRequest(BaseModel):
    updates: list[ThresholdUpdateItem] = []
    # Keys to put back to the default for this server.
    reset: list[str] = []
    updated_by: str = "admin"


_PLUGIN_LOADERS = frozenset({"paper", "purpur", "spigot", "bukkit", "folia", "pufferfish"})


def _applies(server: GameServer, key: str) -> bool:
    """A server reads only its own anticheat's thresholds: Paper-type servers the VoidRP
    Guard plugin's (``guard_*``), servers on mods the voidrp_anticheat mod's."""
    plugin_server = (server.loader or "").lower() in _PLUGIN_LOADERS
    return key.startswith("guard_") == plugin_server


def _config_for(session: Session, server: GameServer) -> list[ThresholdConfigOut]:
    rows = session.query(AnticheatThresholdConfig).filter(
        (AnticheatThresholdConfig.server_id.is_(None)) | (AnticheatThresholdConfig.server_id == server.id)
    ).all()
    defaults = {r.key: r for r in rows if r.server_id is None}
    own = {r.key: r for r in rows if r.server_id is not None}
    out = []
    for key in sorted(k for k in defaults if _applies(server, k)):
        d = defaults[key]
        o = own.get(key)
        shown = o or d
        out.append(ThresholdConfigOut(
            key=key, value=shown.value, label=d.label, description=d.description,
            min_value=d.min_value, max_value=d.max_value, step=d.step,
            updated_by=shown.updated_by, updated_at=shown.updated_at.isoformat(),
            default_value=d.value, overridden=o is not None,
        ))
    return out


@router.get("/config", response_model=list[ThresholdConfigOut])
def get_config(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[ThresholdConfigOut]:
    _ensure_defaults(session)
    return _config_for(session, server)


@router.put("/config", response_model=list[ThresholdConfigOut], dependencies=[Depends(require_permission("anticheat.manage"))])
def update_config(
    req: ThresholdUpdateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> list[ThresholdConfigOut]:
    """Sets values for the server chosen in the admin panel only; others keep theirs."""
    _ensure_defaults(session)
    defaults = {
        r.key: r for r in session.query(AnticheatThresholdConfig)
        .filter(AnticheatThresholdConfig.server_id.is_(None)).all()
    }
    own = {
        r.key: r for r in session.query(AnticheatThresholdConfig)
        .filter(AnticheatThresholdConfig.server_id == server.id).all()
    }
    for key in req.reset:
        if key in own:
            session.delete(own.pop(key))
    for item in req.updates:
        d = defaults.get(item.key)
        if d is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown config key: {item.key}")
        if not _applies(server, item.key):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"«{d.label}» не относится к античиту этого сервера")
        # Only enforce the lower bound (a sane floor); admins may raise a threshold
        # above the recommended slider range by typing it into the number field.
        value = max(d.min_value, item.value)
        row = own.get(item.key)
        if row is None:
            row = AnticheatThresholdConfig(
                server_id=server.id, key=d.key, value=value, label=d.label, description=d.description,
                min_value=d.min_value, max_value=d.max_value, step=d.step,
            )
            session.add(row)
            own[item.key] = row
        row.value = value
        row.updated_by = actor.site_login
    session.commit()
    record_audit(session, actor=actor, category="anticheat", action="config",
                 target_type="server", target_id=str(server.id), target_label=server.slug,
                 server_id=server.id,
                 meta={"updates": {u.key: u.value for u in req.updates}, "reset": req.reset})
    return _config_for(session, server)


# ── Actions carried out by the game server (CoreProtect) ──────────────────────

_ACTION_KINDS = {"rollback", "restore"}


class ActionOut(BaseModel):
    id: str
    kind: str
    target_uuid: str | None
    target_nick: str | None
    params: dict
    status: str
    result: str | None
    created_by: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


def _action_out(a: AnticheatAction) -> ActionOut:
    return ActionOut(
        id=str(a.id), kind=a.kind, target_uuid=a.target_uuid, target_nick=a.target_nick,
        params=a.params or {}, status=a.status, result=a.result, created_by=a.created_by,
        created_at=a.created_at.isoformat(),
        started_at=a.started_at.isoformat() if a.started_at else None,
        finished_at=a.finished_at.isoformat() if a.finished_at else None,
    )


class CreateActionRequest(BaseModel):
    kind: str                       # rollback | restore
    target_nick: str
    target_uuid: str | None = None
    minutes: int                    # how far back
    radius: int = 0                 # blocks round the place; 0 = everywhere
    world: str | None = None
    x: int | None = None
    y: int | None = None
    z: int | None = None
    reason: str = ""


@router.get("/actions", response_model=list[ActionOut])
def list_actions(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    player_uuid: str | None = Query(default=None),
    player_nick: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActionOut]:
    q = session.query(AnticheatAction).filter(AnticheatAction.server_id == server.id)
    if player_uuid:
        q = q.filter(AnticheatAction.target_uuid == player_uuid)
    if player_nick:
        q = q.filter(func.lower(AnticheatAction.target_nick) == player_nick.lower())
    return [_action_out(a) for a in q.order_by(AnticheatAction.created_at.desc()).limit(limit).all()]


@router.post("/actions", response_model=ActionOut, dependencies=[Depends(require_permission("anticheat.manage"))])
def create_action(
    req: CreateActionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> ActionOut:
    """Queues a rollback (or its undo) of one player's changes for the server's plugin."""
    if req.kind not in _ACTION_KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {req.kind}")
    nick = req.target_nick.strip()
    if not nick or len(nick) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Player nickname is required")
    if not 1 <= req.minutes <= 60 * 24 * 30:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Time must be from 1 minute to 30 days")
    if not 0 <= req.radius <= 1000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Radius must be from 0 to 1000 blocks")
    if req.radius and (req.world is None or req.x is None or req.y is None or req.z is None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A radius needs a place: world and coordinates")
    params = {"minutes": req.minutes, "radius": req.radius}
    if req.radius:
        params.update({"world": req.world, "x": req.x, "y": req.y, "z": req.z})
    if req.reason:
        params["reason"] = req.reason[:256]
    action = AnticheatAction(
        server_id=server.id, kind=req.kind, target_uuid=req.target_uuid, target_nick=nick,
        params=params, status="pending", created_by=actor.site_login,
    )
    session.add(action)
    session.commit()
    record_audit(session, actor=actor, category="anticheat", action=req.kind,
                 target_type="player", target_id=req.target_uuid or nick, target_label=nick,
                 server_id=server.id, meta=params)
    return _action_out(action)


# ── Statistics ────────────────────────────────────────────────────────────────

class CheckStats(BaseModel):
    check_type: str
    count: int
    avg_actual: float
    min_actual: float
    max_actual: float
    avg_expected_max: float


class AnticheatStats(BaseModel):
    total_violations: int
    unique_players: int
    by_check: list[CheckStats]


@router.get("/stats", response_model=AnticheatStats)
def get_stats(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> AnticheatStats:
    total = (
        session.query(func.count(AnticheatViolation.id))
        .filter(AnticheatViolation.server_id == server.id)
        .scalar()
        or 0
    )
    unique = (
        session.query(func.count(func.distinct(AnticheatViolation.player_uuid)))
        .filter(AnticheatViolation.server_id == server.id)
        .scalar()
        or 0
    )

    rows = (
        session.query(
            AnticheatViolation.check_type,
            func.count(AnticheatViolation.id).label("cnt"),
            func.avg(AnticheatViolation.actual_value).label("avg_actual"),
            func.min(AnticheatViolation.actual_value).label("min_actual"),
            func.max(AnticheatViolation.actual_value).label("max_actual"),
            func.avg(AnticheatViolation.expected_max).label("avg_expected_max"),
        )
        .filter(AnticheatViolation.server_id == server.id)
        .group_by(AnticheatViolation.check_type)
        .order_by(func.count(AnticheatViolation.id).desc())
        .all()
    )

    by_check = [
        CheckStats(
            check_type=r.check_type,
            count=r.cnt,
            avg_actual=round(r.avg_actual or 0, 3),
            min_actual=round(r.min_actual or 0, 3),
            max_actual=round(r.max_actual or 0, 3),
            avg_expected_max=round(r.avg_expected_max or 0, 3),
        )
        for r in rows
    ]

    return AnticheatStats(total_violations=total, unique_players=unique, by_check=by_check)
