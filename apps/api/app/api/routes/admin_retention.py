"""«Возврат игроков» (core/retention.py): settings, numbers and a test delivery, per server."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import retention, votes
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
            "allowed_commands": sorted(retention.ALLOWED_COMMANDS), "stats": retention.stats(session, server),
            "votes": {"presets": votes.PRESETS, "stats": votes.stats(session, server),
                      "url": f"{get_settings().public_api_url.rstrip('/')}/api/v1/votes/{server.slug}/"}}


class StreakStep(BaseModel):
    day: int = Field(ge=2, le=60)
    message: str = Field(default="", max_length=240)
    commands: list[str] = Field(default_factory=list, max_length=10)


class VoteProvider(BaseModel):
    key: str = Field(max_length=32)
    name: str = Field(default="", max_length=60)
    secret: str = Field(default="", max_length=200)
    nick_field: str = Field(default="nick", max_length=40)
    time_field: str = Field(default="time", max_length=40)
    sign_field: str = Field(default="sign", max_length=40)
    algo: str = Field(default="sha1", max_length=8)
    formula: str = Field(default="{nick}{time}{secret}", max_length=120)
    ok_text: str = Field(default="ok", max_length=40)
    max_skew_minutes: int = Field(default=60, ge=0, le=1440)


class VoteSettings(BaseModel):
    enabled: bool = False
    message: str = Field(default="", max_length=240)
    commands: list[str] = Field(default_factory=list, max_length=10)
    providers: list[VoteProvider] = Field(default_factory=list, max_length=12)


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
    tg_bonus_enabled: bool = False
    tg_bonus_message: str = Field(default="", max_length=240)
    tg_bonus_commands: list[str] = Field(default_factory=list, max_length=10)
    referral_enabled: bool = False
    referral_invited_message: str = Field(default="", max_length=240)
    referral_invited_commands: list[str] = Field(default_factory=list, max_length=10)
    referral_inviter_message: str = Field(default="", max_length=240)
    referral_inviter_commands: list[str] = Field(default_factory=list, max_length=10)
    votes: VoteSettings = Field(default_factory=VoteSettings)
    streak_enabled: bool = False
    streak: list[StreakStep] = Field(default_factory=list, max_length=10)


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

    def clean(commands: list[str], where: str) -> list[str]:
        out = [c.strip().lstrip("/") for c in commands if c.strip()]
        for c in out:
            if err := retention.validate_command(c):
                raise HTTPException(status_code=422, detail=f"{where}: {err}")
        return out

    tg_cmds = clean(payload.tg_bonus_commands, "Бонус за Telegram")
    ref_inv = clean(payload.referral_invited_commands, "Награда приглашённому")
    ref_owner = clean(payload.referral_inviter_commands, "Награда пригласившему")
    vote_cmds = clean(payload.votes.commands, "Награда за голос")
    from apps.api.app.core import votes as _votes

    providers = [p.model_dump() for p in payload.votes.providers]
    keys = [p["key"] for p in providers]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Мониторинги: ключи не должны повторяться")
    for p in providers:
        if err := _votes.validate_provider(p):
            raise HTTPException(status_code=422, detail=f"Мониторинг: {err}")
    days = [st.day for st in payload.streak]
    if len(days) != len(set(days)):
        raise HTTPException(status_code=422, detail="Серия: дни не должны повторяться")
    streak = sorted(({"day": st.day, "message": st.message.strip(), "commands": clean(st.commands, f"Серия, {st.day}-й день")}
                     for st in payload.streak), key=lambda x: x["day"])
    srv = session.get(GameServer, server.id)
    srv.retention_settings = {**payload.model_dump(), "commands": cmds, "welcome_lines": lines,
                              "tg_bonus_commands": tg_cmds, "streak": streak,
                              "referral_invited_commands": ref_inv, "referral_inviter_commands": ref_owner,
                              "votes": {**payload.votes.model_dump(), "commands": vote_cmds, "providers": providers}}
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
