"""«Возврат игроков» (core/retention.py): settings, numbers and a test delivery, per server."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.core import retention
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User

router = APIRouter(prefix="/admin/retention", tags=["admin", "retention"])
_Db = Annotated[Session, Depends(get_db_session)]
_Server = Annotated[GameServer, Depends(resolve_server)]


@router.get("", dependencies=[Depends(require_permission("retention.view"))])
def overview(server: _Server, session: _Db) -> dict:
    return {"server": {"slug": server.slug, "name": server.name, "is_external": server.is_external},
            "settings": retention.settings(server), "defaults": retention.DEFAULTS,
            "allowed_commands": sorted(retention.ALLOWED_COMMANDS), "stats": retention.stats(session, server)}


class RetentionSettings(BaseModel):
    enabled: bool = False
    window_days: int = Field(default=2, ge=1, le=7)
    reward_label: str = Field(default="награда за возвращение", max_length=80)
    reward_message: str = Field(default="", max_length=240)
    commands: list[str] = Field(default_factory=list, max_length=10)
    welcome_enabled: bool = False
    welcome_lines: list[str] = Field(default_factory=list, max_length=6)
    reminder_enabled: bool = True
    reminder_text: str = Field(default="", max_length=400)


@router.put("/settings", dependencies=[Depends(require_permission("retention.manage"))])
def put_settings(payload: RetentionSettings, server: _Server, session: _Db,
                 actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    cmds = [c.strip().lstrip("/") for c in payload.commands if c.strip()]
    for c in cmds:
        if err := retention.validate_command(c):
            raise HTTPException(status_code=422, detail=f"Команда награды: {err}")
    lines = [x.strip()[:240] for x in payload.welcome_lines if x.strip()]
    if payload.enabled and not cmds:
        raise HTTPException(status_code=422, detail="Добавьте хотя бы одну команду награды")
    srv = session.get(GameServer, server.id)
    srv.retention_settings = {**payload.model_dump(), "commands": cmds, "welcome_lines": lines}
    record_audit(session, category="retention", action="settings", actor=actor, target_type="server",
                 target_id=str(srv.id), target_label=srv.slug, server_id=srv.id,
                 meta={"enabled": payload.enabled, "commands": cmds})
    return {"settings": retention.settings(srv)}


class TestRequest(BaseModel):
    nickname: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")


@router.post("/test", dependencies=[Depends(require_permission("retention.manage"))])
def test(payload: TestRequest, server: _Server, session: _Db, actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    """Gives the reward to a player in game now (to check the commands) — not counted as theirs."""
    row = retention.queue_test(session, server, payload.nickname, actor.site_login)
    record_audit(session, category="retention", action="test", actor=actor, target_type="player",
                 target_id=payload.nickname, target_label=payload.nickname, server_id=server.id)
    return {"id": row.id, "detail": "Награда уйдёт в течение минуты, если игрок в игре"}
