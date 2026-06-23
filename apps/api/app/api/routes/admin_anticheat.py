from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from apps.api.app.core.rcon_client import send_rcon_command
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.models.anticheat import (
    AnticheatInjectionReport,
    AnticheatModSnapshot,
    AnticheatThresholdConfig,
    AnticheatViolation,
    ModVerdict,
)
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user import User

router = APIRouter(
    prefix="/admin/anticheat",
    tags=["admin", "anticheat"],
    dependencies=[Depends(require_admin_access)],
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

def _latest_suspicious(session: Session, player_uuid: str) -> list[str]:
    snap = (
        session.query(AnticheatModSnapshot)
        .filter(AnticheatModSnapshot.player_uuid == player_uuid)
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
        .group_by(AnticheatViolation.player_uuid, AnticheatViolation.player_nick)
        .order_by(func.max(AnticheatViolation.created_at).desc())
    )
    total = q.count()
    rows = q.offset(skip).limit(limit).all()

    items: list[AnticheatPlayerSummary] = []
    for row in rows:
        suspicious = _latest_suspicious(session, row.player_uuid)
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
) -> AnticheatPlayerDetail:
    violations = (
        session.query(AnticheatViolation)
        .filter(AnticheatViolation.player_uuid == player_uuid)
        .order_by(AnticheatViolation.created_at.desc())
        .all()
    )
    snapshots = (
        session.query(AnticheatModSnapshot)
        .filter(AnticheatModSnapshot.player_uuid == player_uuid)
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
        .filter(AnticheatInjectionReport.player_uuid == player_uuid)
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


@router.post("/player/{player_uuid}/action")
def player_action(
    player_uuid: str,
    req: ActionRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, str]:
    violations = (
        session.query(AnticheatViolation)
        .filter(AnticheatViolation.player_uuid == player_uuid)
        .all()
    )
    snapshots = (
        session.query(AnticheatModSnapshot)
        .filter(AnticheatModSnapshot.player_uuid == player_uuid)
        .all()
    )
    if not violations and not snapshots:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    nick = violations[0].player_nick if violations else snapshots[0].player_nick
    reason = req.reason or "Действие администратора"

    if req.action == "kick":
        send_rcon_command(f'kick {nick} {reason}')

    elif req.action in ("disable", "enable"):
        user = _find_user(session, nick)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site account not found")
        user.is_active = req.action == "enable"
        session.commit()
        if req.action == "disable":
            send_rcon_command(f'kick {nick} Аккаунт заблокирован')

    elif req.action == "clear_violations":
        for v in violations:
            v.reviewed = True
            v.review_action = "cleared"
            v.reviewed_by = req.reviewed_by
        session.commit()

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {req.action}")

    return {"ok": "true", "action": req.action, "nick": nick}


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


@router.post("/mod-verdicts", response_model=ModVerdictOut, status_code=200)
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


@router.delete("/mod-verdicts/{mod_id}", status_code=204)
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
    {"key": "vl_threshold", "value": 10.0, "label": "Порог VL", "description": "Сколько VL нужно для репорта нарушения", "min_value": 1.0, "max_value": 100.0, "step": 1.0},
    {"key": "speed_threshold", "value": 0.75, "label": "Скорость (блоков/тик)", "description": "Максимальная горизонтальная скорость без эффектов", "min_value": 0.3, "max_value": 5.0, "step": 0.05},
    {"key": "fly_ticks_threshold", "value": 40.0, "label": "Полёт (тиков)", "description": "Тиков в воздухе без снижения до флага", "min_value": 5.0, "max_value": 200.0, "step": 1.0},
    {"key": "reach_threshold", "value": 6.5, "label": "Дальность удара (блоков)", "description": "Максимальная дистанция атаки", "min_value": 3.0, "max_value": 20.0, "step": 0.5},
    {"key": "killaura_targets_per_second", "value": 6.0, "label": "KillAura: целей в сек", "description": "Максимум разных целей за 1 секунду", "min_value": 2.0, "max_value": 20.0, "step": 1.0},
    {"key": "cps_threshold", "value": 25.0, "label": "Порог CPS", "description": "Максимум кликов в секунду", "min_value": 10.0, "max_value": 50.0, "step": 1.0},
]


def _ensure_defaults(session: Session) -> None:
    from uuid import uuid4
    existing = {r.key for r in session.query(AnticheatThresholdConfig).all()}
    for cfg in _DEFAULT_CONFIGS:
        if cfg["key"] not in existing:
            session.add(AnticheatThresholdConfig(
                key=cfg["key"],
                value=cfg["value"],
                label=cfg["label"],
                description=cfg["description"],
                min_value=cfg["min_value"],
                max_value=cfg["max_value"],
                step=cfg["step"],
            ))
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


class ThresholdUpdateItem(BaseModel):
    key: str
    value: float


class ThresholdUpdateRequest(BaseModel):
    updates: list[ThresholdUpdateItem]
    updated_by: str = "admin"


@router.get("/config", response_model=list[ThresholdConfigOut])
def get_config(
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ThresholdConfigOut]:
    _ensure_defaults(session)
    rows = session.query(AnticheatThresholdConfig).order_by(AnticheatThresholdConfig.key).all()
    return [
        ThresholdConfigOut(
            key=r.key,
            value=r.value,
            label=r.label,
            description=r.description,
            min_value=r.min_value,
            max_value=r.max_value,
            step=r.step,
            updated_by=r.updated_by,
            updated_at=r.updated_at.isoformat(),
        )
        for r in rows
    ]


@router.put("/config", response_model=list[ThresholdConfigOut])
def update_config(
    req: ThresholdUpdateRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ThresholdConfigOut]:
    _ensure_defaults(session)
    rows_map = {r.key: r for r in session.query(AnticheatThresholdConfig).all()}
    for item in req.updates:
        if item.key not in rows_map:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown config key: {item.key}")
        row = rows_map[item.key]
        clamped = max(row.min_value, min(row.max_value, item.value))
        row.value = clamped
        row.updated_by = req.updated_by
    session.commit()
    rows = session.query(AnticheatThresholdConfig).order_by(AnticheatThresholdConfig.key).all()
    return [
        ThresholdConfigOut(
            key=r.key,
            value=r.value,
            label=r.label,
            description=r.description,
            min_value=r.min_value,
            max_value=r.max_value,
            step=r.step,
            updated_by=r.updated_by,
            updated_at=r.updated_at.isoformat(),
        )
        for r in rows
    ]


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
) -> AnticheatStats:
    total = session.query(func.count(AnticheatViolation.id)).scalar() or 0
    unique = session.query(func.count(func.distinct(AnticheatViolation.player_uuid))).scalar() or 0

    rows = (
        session.query(
            AnticheatViolation.check_type,
            func.count(AnticheatViolation.id).label("cnt"),
            func.avg(AnticheatViolation.actual_value).label("avg_actual"),
            func.min(AnticheatViolation.actual_value).label("min_actual"),
            func.max(AnticheatViolation.actual_value).label("max_actual"),
            func.avg(AnticheatViolation.expected_max).label("avg_expected_max"),
        )
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
