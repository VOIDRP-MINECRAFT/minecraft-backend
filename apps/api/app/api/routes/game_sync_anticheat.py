from __future__ import annotations

import json
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.models.anticheat import (
    AnticheatInjectionReport,
    AnticheatModSnapshot,
    AnticheatThresholdConfig,
    AnticheatViolation,
    ModVerdict,
)

router = APIRouter(
    prefix="/anticheat",
    tags=["anticheat", "game-sync"],
    dependencies=[Depends(require_game_auth_secret)],
)

# ── Known cheat mod IDs (substring match against modid, before the colon) ─────
# Keep keywords specific enough to avoid hitting legitimate mods.
# "rise" removed — it's a substring of "arise" (dungeons_arise, etc.);
# use the more specific "riseclient" instead.
_CHEAT_MOD_KEYWORDS = [
    "wurst", "sigma", "future", "liquidbounce", "aristois", "meteor",
    "xaero_hack", "blatant", "rusherhack", "wolfram",
    "entropy", "riseclient", "kami", "nocom",
    # "impact", "inertia", "crystal" removed — too many false positives
    # with legitimate content mods; flag only if exact ID matches below
]

# Exact cheat mod IDs (full modid, before the colon)
_EXACT_CHEAT_MOD_IDS: frozenset[str] = frozenset({
    "rise", "impact", "inertia", "crystal", "kamiclient",
    "wh", "esp", "xray", "noclip", "killaura",
})

# Legitimate mods whose ID happens to contain a cheat keyword — never flag
_SAFE_MOD_IDS: frozenset[str] = frozenset({
    "dungeons_arise", "dungeonsarise",       # "arise" contains "rise"
    "crystalcaves", "crystal_clear",          # "crystal" prefix
    "impactful", "impact_enchant",            # "impact"
    "inertia_tweaks",                         # "inertia"
    "sigma_core",                             # legitimate sigma-core library
    "future_mc",                              # backport mod, not a cheat
    "meteorite", "meteor_client_compat",      # "meteor" legitimate uses
    "kamicommon",                             # "kami" common library
})


def _mod_base(mod: str) -> str:
    """Return the mod ID without version (strip ':...' suffix)."""
    return mod.split(":")[0].lower()


def _load_verdicts(session: Session) -> tuple[frozenset[str], frozenset[str]]:
    """Returns (cheat_ids, safe_ids) from admin-reviewed verdicts."""
    cheats, safes = set(), set()
    for v in session.query(ModVerdict).all():
        (cheats if v.verdict == "CHEAT" else safes).add(v.mod_id.lower())
    return frozenset(cheats), frozenset(safes)


def _find_suspicious(mods: list[str], session: Session) -> list[str]:
    cheat_ids, safe_ids = _load_verdicts(session)
    flagged = []
    for mod in mods:
        base = _mod_base(mod)
        if base in _SAFE_MOD_IDS or base in safe_ids:
            continue
        if base in cheat_ids or base in _EXACT_CHEAT_MOD_IDS:
            flagged.append(mod)
            continue
        for kw in _CHEAT_MOD_KEYWORDS:
            if kw in base:
                flagged.append(mod)
                break
    return flagged


@router.get("/config")
def get_anticheat_config(
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, float]:
    """Returns current threshold config for the game server mod to poll."""
    rows = session.query(AnticheatThresholdConfig).all()
    return {r.key: r.value for r in rows}


class ViolationRequest(BaseModel):
    player_uuid: str
    player_nick: str
    check_type: str
    details: str = ""
    actual_value: float = 0.0
    expected_max: float = 0.0
    vl: int = 0
    severity: str = "LOW"


class ModSnapshotRequest(BaseModel):
    player_uuid: str
    player_nick: str
    mods: list[str]


@router.post("/violation", status_code=204)
def ingest_violation(
    req: ViolationRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    record = AnticheatViolation(
        id=str(uuid4()),
        player_uuid=req.player_uuid,
        player_nick=req.player_nick,
        check_type=req.check_type,
        details=req.details,
        actual_value=req.actual_value,
        expected_max=req.expected_max,
        vl=req.vl,
        severity=req.severity,
    )
    session.add(record)
    session.commit()


@router.post("/mod-snapshot", status_code=204)
def ingest_mod_snapshot(
    req: ModSnapshotRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    suspicious = _find_suspicious(req.mods, session)
    record = AnticheatModSnapshot(
        id=str(uuid4()),
        player_uuid=req.player_uuid,
        player_nick=req.player_nick,
        mods=json.dumps(req.mods),
        suspicious_mods=json.dumps(suspicious),
        is_verified=True,
    )
    session.add(record)
    session.commit()


class InjectionReportRequest(BaseModel):
    player_uuid: str
    player_nick: str
    java_agents: list[str] = []
    suspicious_libraries: list[str] = []
    agents_detected: bool = False


@router.post("/injection-report", status_code=204)
def ingest_injection_report(
    req: InjectionReportRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    record = AnticheatInjectionReport(
        id=str(uuid4()),
        player_uuid=req.player_uuid,
        player_nick=req.player_nick,
        java_agents=json.dumps(req.java_agents),
        suspicious_libraries=json.dumps(req.suspicious_libraries),
        agents_detected=req.agents_detected,
    )
    session.add(record)
    session.commit()
