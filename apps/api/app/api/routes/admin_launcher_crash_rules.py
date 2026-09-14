from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.launcher_crash_report import LauncherCrashReport
from apps.api.app.models.launcher_crash_rule import LauncherCrashRule
from apps.api.app.repositories.game_server_repository import GameServerRepository
from apps.api.app.services.launcher_crash_rules_service import (
    ACTION_TYPES,
    DEFAULT_RECOMMENDED_RAM_MB,
    classify_report,
    effective_rules,
    load_builtin_rules,
    match_rule,
    report_haystack,
    rule_to_dict,
    validate_rule,
)

router = APIRouter(
    prefix="/admin/launcher-crash-rules",
    tags=["admin", "launcher-crash-rules"],
    dependencies=[Depends(require_permission("crashes.view"))],
)

_manage = [Depends(require_permission("crashes.rules.manage"))]


class CrashRuleAction(BaseModel):
    type: str
    label: str = ""
    paths: list[str] = Field(default_factory=list)


class CrashRuleBody(BaseModel):
    key: str
    server_slug: str | None = None   # None = every server
    priority: int = Field(default=0, ge=-1000, le=1000)
    enabled: bool = True
    patterns_all: list[str] = Field(default_factory=list)
    patterns_any: list[str] = Field(default_factory=list)
    exit_codes: list[int] = Field(default_factory=list)
    title: str
    cause: str = ""
    solution: str = ""
    actions: list[CrashRuleAction] = Field(default_factory=list)


class CrashRuleItem(BaseModel):
    id: str
    server_slug: str | None
    key: str
    priority: int
    enabled: bool
    patterns_all: list[str]
    patterns_any: list[str]
    exit_codes: list[int]
    title: str
    cause: str
    solution: str
    actions: list[dict[str, Any]]
    overrides_builtin: bool
    updated_at: str


class TestRuleBody(BaseModel):
    patterns_all: list[str] = Field(default_factory=list)
    patterns_any: list[str] = Field(default_factory=list)
    exit_codes: list[int] = Field(default_factory=list)
    server_slug: str | None = None
    limit: int = Field(default=300, ge=1, le=1000)


class RamSettingBody(BaseModel):
    server_slug: str
    launcher_recommended_ram_mb: int | None = Field(default=None, ge=1024, le=65536)


def _servers_by_id(session: Session) -> dict[UUID, GameServer]:
    return {s.id: s for s in GameServerRepository(session).list_all()}


def _server_or_404(session: Session, slug: str | None) -> GameServer | None:
    if not slug:
        return None
    server = GameServerRepository(session).get_by_slug(slug)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сервер не найден.")
    return server


def _item(rule: LauncherCrashRule, servers: dict[UUID, GameServer]) -> CrashRuleItem:
    builtin_keys = {r["key"] for r in load_builtin_rules()}
    data = rule_to_dict(rule)
    return CrashRuleItem(
        id=str(rule.id),
        server_slug=servers[rule.server_id].slug if rule.server_id in servers else None,
        overrides_builtin=rule.key in builtin_keys,
        updated_at=rule.updated_at.isoformat(),
        **data,
    )


def _validated(body: CrashRuleBody) -> dict[str, Any]:
    data = body.model_dump()
    data["actions"] = [a.model_dump() for a in body.actions]
    errors = validate_rule(data)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=" ".join(errors))
    return data


def _ensure_unique(session: Session, key: str, server: GameServer | None, exclude: UUID | None = None) -> None:
    stmt = select(LauncherCrashRule).where(LauncherCrashRule.key == key)
    stmt = stmt.where(LauncherCrashRule.server_id.is_(None) if server is None else LauncherCrashRule.server_id == server.id)
    existing = session.scalars(stmt).first()
    if existing is not None and existing.id != exclude:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Правило с таким ключом для этого сервера уже есть.")


@router.get("")
def list_rules(session: Annotated[Session, Depends(get_db_session)]) -> dict[str, Any]:
    servers = _servers_by_id(session)
    rules = session.scalars(select(LauncherCrashRule).order_by(desc(LauncherCrashRule.priority), LauncherCrashRule.key)).all()
    return {
        "items": [_item(r, servers) for r in rules],
        "action_types": ACTION_TYPES,
        "default_recommended_ram_mb": DEFAULT_RECOMMENDED_RAM_MB,
        "servers": [
            {"slug": s.slug, "name": s.name, "launcher_recommended_ram_mb": s.launcher_recommended_ram_mb}
            for s in servers.values()
        ],
    }


@router.get("/builtin")
def list_builtin_rules() -> dict[str, Any]:
    """Rules compiled into the launcher; a DB rule with the same key overrides or disables one."""
    return {"items": load_builtin_rules()}


@router.post("", response_model=CrashRuleItem, dependencies=_manage)
def create_rule(body: CrashRuleBody, session: Annotated[Session, Depends(get_db_session)]) -> CrashRuleItem:
    data = _validated(body)
    server = _server_or_404(session, body.server_slug)
    _ensure_unique(session, body.key, server)
    data.pop("server_slug")
    rule = LauncherCrashRule(server_id=server.id if server else None, **data)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return _item(rule, _servers_by_id(session))


@router.put("/{rule_id}", response_model=CrashRuleItem, dependencies=_manage)
def update_rule(rule_id: UUID, body: CrashRuleBody, session: Annotated[Session, Depends(get_db_session)]) -> CrashRuleItem:
    rule = session.get(LauncherCrashRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено.")
    data = _validated(body)
    server = _server_or_404(session, body.server_slug)
    _ensure_unique(session, body.key, server, exclude=rule.id)
    data.pop("server_slug")
    rule.server_id = server.id if server else None
    for name, value in data.items():
        setattr(rule, name, value)
    session.commit()
    session.refresh(rule)
    return _item(rule, _servers_by_id(session))


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_manage)
def delete_rule(rule_id: UUID, session: Annotated[Session, Depends(get_db_session)]) -> None:
    rule = session.get(LauncherCrashRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()


@router.post("/test")
def test_rule(body: TestRuleBody, session: Annotated[Session, Depends(get_db_session)]) -> dict[str, Any]:
    """Runs a (possibly unsaved) rule over recent crash reports so the admin sees what it would catch."""
    rule = {"key": "test", "patterns_all": body.patterns_all, "patterns_any": body.patterns_any, "exit_codes": body.exit_codes}
    errors = [e for e in validate_rule({**rule, "title": "test", "key": "test_rule"}) if "Шаблон" in e or "шаблон" in e]
    if errors:
        return {"tested": 0, "matched": 0, "samples": [], "errors": errors}

    stmt = select(LauncherCrashReport).order_by(desc(LauncherCrashReport.created_at)).limit(body.limit)
    if body.server_slug:
        stmt = stmt.where(LauncherCrashReport.server_slug == body.server_slug)
    reports = session.scalars(stmt).all()

    samples: list[dict[str, Any]] = []
    matched = 0
    for report in reports:
        result = match_rule(rule, report.exit_code, report_haystack(report))
        if not result.matched:
            continue
        matched += 1
        if len(samples) < 20:
            samples.append({
                "id": str(report.id),
                "player_nickname": report.player_nickname,
                "created_at": report.created_at.isoformat(),
                "exit_code": report.exit_code,
                "advice_rule_key": report.advice_rule_key,
                "snippet": result.snippet,
                "captures": result.captures,
            })
    return {"tested": len(reports), "matched": matched, "samples": samples, "errors": []}


@router.get("/coverage")
def coverage(
    session: Annotated[Session, Depends(get_db_session)],
    days: int = Query(default=14, ge=1, le=90),
) -> dict[str, Any]:
    """How the current rules (built-ins + DB) would classify the last ``days`` of crash reports."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    reports = session.scalars(
        select(LauncherCrashReport).where(LauncherCrashReport.created_at >= since).order_by(desc(LauncherCrashReport.created_at))
    ).all()

    repo = GameServerRepository(session)
    default_server = repo.get_default()
    rules_cache: dict[str | None, list[dict[str, Any]]] = {}
    counts: Counter[str] = Counter()
    unrecognized: list[dict[str, Any]] = []
    for report in reports:
        slug = report.server_slug
        if slug not in rules_cache:
            server = repo.get_by_slug(slug) if slug else default_server
            rules_cache[slug] = effective_rules(session, server)
        key = classify_report(rules_cache[slug], report)
        if key:
            counts[key] += 1
        else:
            counts["<unrecognized>"] += 1
            if len(unrecognized) < 30:
                unrecognized.append({
                    "id": str(report.id),
                    "player_nickname": report.player_nickname,
                    "created_at": report.created_at.isoformat(),
                    "exit_code": report.exit_code,
                })
    total = len(reports)
    return {
        "days": days,
        "total": total,
        "recognized": total - counts.get("<unrecognized>", 0),
        "by_rule": [{"key": k, "count": c} for k, c in counts.most_common()],
        "unrecognized_samples": unrecognized,
    }


@router.post("/settings", dependencies=_manage)
def update_ram_setting(body: RamSettingBody, session: Annotated[Session, Depends(get_db_session)]) -> dict[str, Any]:
    server = _server_or_404(session, body.server_slug)
    assert server is not None
    server.launcher_recommended_ram_mb = body.launcher_recommended_ram_mb
    session.commit()
    return {"server_slug": server.slug, "launcher_recommended_ram_mb": server.launcher_recommended_ram_mb}
