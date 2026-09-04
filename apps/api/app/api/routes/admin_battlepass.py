from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, func, select, update as sa_update
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.battlepass_reward import BattlePassReward
from apps.api.app.models.battlepass_season import BattlePassSeason
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.battlepass import (
    AdminBattlePassPlayerInfo,
    BattlePassPremiumGrantRequest,
    BattlePassPremiumListResponse,
    BattlePassPremiumResponse,
)
from apps.api.app.services.battlepass_service import (
    BattlePassNotFoundError,
    BattlePassService,
)

router = APIRouter(
    prefix="/admin/battlepass",
    tags=["admin", "battlepass"],
    dependencies=[Depends(require_permission("battlepass.view"))],
)


def get_battlepass_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BattlePassService:
    return BattlePassService(session=session, server_id=server.id)


@router.get("/premium", response_model=BattlePassPremiumListResponse)
def list_premium(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    active_only: bool = Query(default=True),
    service: Annotated[BattlePassService, Depends(get_battlepass_service)] = None,
) -> BattlePassPremiumListResponse:
    assert service is not None
    if active_only:
        return service.list_active_premium(skip=skip, limit=limit)
    return service.list_all_premium(skip=skip, limit=limit)


@router.post("/premium/grant", response_model=BattlePassPremiumResponse, dependencies=[Depends(require_permission("battlepass.manage"))])
def admin_grant_premium(
    payload: BattlePassPremiumGrantRequest,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> BattlePassPremiumResponse:
    return service.grant_premium(payload, granted_by="admin")


@router.delete("/premium/{minecraft_uuid}", dependencies=[Depends(require_permission("battlepass.manage"))])
def revoke_premium(
    minecraft_uuid: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> dict[str, bool]:
    try:
        service.revoke_premium(minecraft_uuid)
    except BattlePassNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {"ok": True}


@router.post("/premium/revoke-by-nick/{nickname}", dependencies=[Depends(require_permission("battlepass.manage"))])
def revoke_premium_by_nick(
    nickname: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> dict[str, bool]:
    """Revoke by nickname: updates DB if record exists, always sends RCON."""
    service.revoke_premium_by_nick(nickname)
    return {"ok": True}


@router.get("/player-by-nick/{nickname}", response_model=AdminBattlePassPlayerInfo)
def get_player_by_nick(
    nickname: str,
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> AdminBattlePassPlayerInfo:
    return service.get_admin_player_info_by_nick(nickname)


@router.get("/stats")
def get_stats(
    service: Annotated[BattlePassService, Depends(get_battlepass_service)],
) -> dict[str, int]:
    return service.get_stats()


# ── Seasons (dates / level cap / active) ─────────────────────────────────────
MAX_BP_LEVEL = 500      # hard cap for a slot's level (a season's own max_level constrains the UI)
_TRACKS = {"free", "premium"}
_RTYPES = {"command", "item", "money", "voidcoin"}
# Rewards + seasons editing is a distinct permission from premium-granting (battlepass.manage),
# so a moderator can be given one without the other (grantable at /admin/moderators).
_MANAGE = Depends(require_permission("battlepass.rewards.manage"))


class SeasonOut(BaseModel):
    id: str
    season_key: str
    name: str
    start_date: date
    end_date: date
    max_level: int
    is_active: bool
    reward_count: int = 0


class SeasonCreate(BaseModel):
    season_key: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    start_date: date
    end_date: date
    max_level: int = Field(default=100, ge=1, le=MAX_BP_LEVEL)
    activate: bool = False
    copy_rewards_from: str | None = Field(default=None, max_length=32)


class SeasonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    start_date: date | None = None
    end_date: date | None = None
    max_level: int | None = Field(default=None, ge=1, le=MAX_BP_LEVEL)
    is_active: bool | None = None


def _season_out(s: BattlePassSeason, reward_count: int = 0) -> SeasonOut:
    return SeasonOut(
        id=str(s.id), season_key=s.season_key, name=s.name, start_date=s.start_date,
        end_date=s.end_date, max_level=s.max_level, is_active=s.is_active, reward_count=reward_count,
    )


def _reward_counts(db: Session, server_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(BattlePassReward.season, func.count())
        .where(BattlePassReward.server_id == server_id)
        .group_by(BattlePassReward.season)
    ).all()
    return {s: int(c) for s, c in rows}


def _get_season(db: Session, server_id: uuid.UUID, key: str) -> BattlePassSeason:
    s = db.execute(
        select(BattlePassSeason).where(
            BattlePassSeason.server_id == server_id,
            BattlePassSeason.season_key == key,
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Сезон не найден.")
    return s


@router.get("/seasons", response_model=list[SeasonOut])
def list_seasons(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[SeasonOut]:
    rows = db.execute(
        select(BattlePassSeason)
        .where(BattlePassSeason.server_id == server.id)
        .order_by(BattlePassSeason.is_active.desc(), BattlePassSeason.start_date.desc())
    ).scalars().all()
    counts = _reward_counts(db, server.id)
    return [_season_out(s, counts.get(s.season_key, 0)) for s in rows]


@router.post("/seasons", response_model=SeasonOut, status_code=status.HTTP_201_CREATED, dependencies=[_MANAGE])
def create_season(
    payload: SeasonCreate,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> SeasonOut:
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=422, detail="Дата окончания раньше даты начала.")
    exists = db.execute(
        select(BattlePassSeason).where(
            BattlePassSeason.server_id == server.id,
            BattlePassSeason.season_key == payload.season_key,
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="Сезон с таким ключом уже есть.")
    if payload.activate:
        db.execute(sa_update(BattlePassSeason)
                   .where(BattlePassSeason.server_id == server.id)
                   .values(is_active=False))
    row = BattlePassSeason(
        id=uuid.uuid4(), server_id=server.id, season_key=payload.season_key, name=payload.name.strip(),
        start_date=payload.start_date, end_date=payload.end_date, max_level=payload.max_level,
        is_active=payload.activate,
    )
    db.add(row)

    copied = 0
    if payload.copy_rewards_from:
        src = db.execute(
            select(BattlePassReward).where(
                BattlePassReward.server_id == server.id,
                BattlePassReward.season == payload.copy_rewards_from,
            )
        ).scalars().all()
        for r in src:
            db.add(BattlePassReward(
                id=uuid.uuid4(), server_id=server.id, season=payload.season_key,
                level=r.level, track=r.track, reward_type=r.reward_type,
                command=r.command, material=r.material, item_key=r.item_key,
                count=r.count, amount=r.amount, display_name=r.display_name, icon=r.icon,
            ))
            copied += 1
    db.commit()
    db.refresh(row)
    return _season_out(row, copied)


@router.patch("/seasons/{season_key}", response_model=SeasonOut, dependencies=[_MANAGE])
def update_season(
    season_key: str,
    payload: SeasonUpdate,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> SeasonOut:
    s = _get_season(db, server.id, season_key)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        s.name = data["name"].strip()
    if "start_date" in data and data["start_date"]:
        s.start_date = data["start_date"]
    if "end_date" in data and data["end_date"]:
        s.end_date = data["end_date"]
    if "max_level" in data and data["max_level"]:
        s.max_level = int(data["max_level"])
    if s.end_date < s.start_date:
        raise HTTPException(status_code=422, detail="Дата окончания раньше даты начала.")
    if data.get("is_active") is True:
        db.execute(sa_update(BattlePassSeason)
                   .where(BattlePassSeason.server_id == server.id,
                          BattlePassSeason.id != s.id)
                   .values(is_active=False))
        s.is_active = True
    elif data.get("is_active") is False:
        s.is_active = False
    db.commit()
    db.refresh(s)
    counts = _reward_counts(db, server.id)
    return _season_out(s, counts.get(s.season_key, 0))


@router.delete("/seasons/{season_key}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_MANAGE])
def delete_season(
    season_key: str,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> None:
    s = _get_season(db, server.id, season_key)
    if s.is_active:
        raise HTTPException(status_code=409, detail="Нельзя удалить активный сезон — сначала активируйте другой.")
    db.execute(sa_delete(BattlePassReward).where(
        BattlePassReward.server_id == server.id,
        BattlePassReward.season == season_key,
    ))
    db.delete(s)
    db.commit()


# ── Reward table editor (per season / level / track) ─────────────────────────
class RewardSlotOut(BaseModel):
    id: str
    season: str
    level: int
    track: str
    reward_type: str
    command: str | None = None
    material: str | None = None
    item_key: str | None = None
    count: int | None = None
    amount: int | None = None
    display_name: str | None = None
    icon: str | None = None


class RewardSlotUpsert(BaseModel):
    season: str = Field(..., min_length=4, max_length=32)
    level: int = Field(..., ge=1, le=MAX_BP_LEVEL)
    track: str = Field(..., pattern=r"^(free|premium)$")
    reward_type: str = Field(..., pattern=r"^(command|item|money|voidcoin)$")
    command: str | None = Field(default=None, max_length=512)
    material: str | None = Field(default=None, max_length=64)
    item_key: str | None = Field(default=None, max_length=128)
    count: int | None = Field(default=None, ge=1, le=6400)
    amount: int | None = Field(default=None, ge=0, le=10_000_000_000)
    display_name: str | None = Field(default=None, max_length=128)
    icon: str | None = Field(default=None, max_length=128)


class SeasonInfo(BaseModel):
    season: str
    count: int


class CopySeasonRequest(BaseModel):
    from_season: str = Field(..., min_length=4, max_length=32)
    to_season: str = Field(..., min_length=4, max_length=32)
    overwrite: bool = False


def _reward_out(r: BattlePassReward) -> RewardSlotOut:
    return RewardSlotOut(
        id=str(r.id), season=r.season, level=r.level, track=r.track,
        reward_type=r.reward_type, command=r.command, material=r.material,
        item_key=r.item_key, count=r.count,
        amount=(int(r.amount) if r.amount is not None else None),
        display_name=r.display_name, icon=r.icon,
    )


def _validate_slot(p: RewardSlotUpsert) -> None:
    if p.reward_type in ("money", "voidcoin"):
        if p.amount is None or p.amount <= 0:
            raise HTTPException(status_code=422, detail="Для награды-валюты укажите amount > 0.")
    elif p.reward_type == "item":
        if not (p.material and p.material.strip()):
            raise HTTPException(status_code=422, detail="Для предмета укажите material.")
    elif p.reward_type == "command":
        if not (p.command and p.command.strip()):
            raise HTTPException(status_code=422, detail="Для команды укажите command.")


@router.get("/rewards/seasons", response_model=list[SeasonInfo])
def list_reward_seasons(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[SeasonInfo]:
    rows = db.execute(
        select(BattlePassReward.season, func.count())
        .where(BattlePassReward.server_id == server.id)
        .group_by(BattlePassReward.season)
        .order_by(BattlePassReward.season.desc())
    ).all()
    return [SeasonInfo(season=s, count=int(c)) for s, c in rows]


@router.get("/rewards", response_model=list[RewardSlotOut])
def list_rewards(
    season: Annotated[str, Query(min_length=4, max_length=32)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[RewardSlotOut]:
    rows = db.execute(
        select(BattlePassReward)
        .where(BattlePassReward.server_id == server.id, BattlePassReward.season == season)
        .order_by(BattlePassReward.level, BattlePassReward.track)
    ).scalars().all()
    return [_reward_out(r) for r in rows]


@router.put("/rewards", response_model=RewardSlotOut, dependencies=[_MANAGE])
def upsert_reward(
    payload: RewardSlotUpsert,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> RewardSlotOut:
    """Create or replace the reward at (season, level, track). Fields not relevant to the
    chosen reward_type are cleared so a slot never carries stale values from a prior type."""
    _validate_slot(payload)
    row = db.execute(
        select(BattlePassReward).where(
            BattlePassReward.server_id == server.id,
            BattlePassReward.season == payload.season,
            BattlePassReward.level == payload.level,
            BattlePassReward.track == payload.track,
        )
    ).scalar_one_or_none()
    if row is None:
        row = BattlePassReward(
            id=uuid.uuid4(), server_id=server.id, season=payload.season,
            level=payload.level, track=payload.track, reward_type=payload.reward_type,
        )
        db.add(row)

    row.reward_type = payload.reward_type
    # clear all optional fields, then set only those relevant to the type
    row.command = row.material = row.item_key = row.icon = None
    row.count = row.amount = None
    row.display_name = (payload.display_name or None)
    if payload.reward_type in ("money", "voidcoin"):
        row.amount = int(payload.amount or 0)
    elif payload.reward_type == "item":
        row.material = payload.material.strip()
        row.count = int(payload.count or 1)
        row.icon = payload.icon or f"minecraft:{row.material.lower()}"
    elif payload.reward_type == "command":
        row.command = payload.command.strip()
        icon = payload.icon
        if not icon:
            for tok in row.command.split(" "):
                if ":" in tok and not tok.lstrip("/").startswith("minecraft:give"):
                    icon = tok
                    break
        row.icon = icon
        row.item_key = icon
    db.commit()
    db.refresh(row)
    return _reward_out(row)


@router.delete("/rewards/{reward_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_MANAGE])
def delete_reward(
    reward_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> None:
    row = db.execute(
        select(BattlePassReward).where(
            BattlePassReward.id == reward_id,
            BattlePassReward.server_id == server.id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Награда не найдена.")
    db.delete(row)
    db.commit()


@router.post("/rewards/copy", response_model=dict, dependencies=[_MANAGE])
def copy_season(
    payload: CopySeasonRequest,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> dict:
    """Copy every reward slot from one season to another (for starting a new season)."""
    if payload.from_season == payload.to_season:
        raise HTTPException(status_code=422, detail="Сезоны совпадают.")
    src = db.execute(
        select(BattlePassReward).where(
            BattlePassReward.server_id == server.id,
            BattlePassReward.season == payload.from_season,
        )
    ).scalars().all()
    if not src:
        raise HTTPException(status_code=404, detail="У исходного сезона нет наград.")
    existing = {
        (r.level, r.track): r
        for r in db.execute(
            select(BattlePassReward).where(
                BattlePassReward.server_id == server.id,
                BattlePassReward.season == payload.to_season,
            )
        ).scalars().all()
    }
    if existing and not payload.overwrite:
        raise HTTPException(status_code=409, detail="В целевом сезоне уже есть награды (overwrite=false).")
    if payload.overwrite:
        db.execute(sa_delete(BattlePassReward).where(
            BattlePassReward.server_id == server.id,
            BattlePassReward.season == payload.to_season,
        ))
    n = 0
    for r in src:
        db.add(BattlePassReward(
            id=uuid.uuid4(), server_id=server.id, season=payload.to_season,
            level=r.level, track=r.track, reward_type=r.reward_type,
            command=r.command, material=r.material, item_key=r.item_key,
            count=r.count, amount=r.amount, display_name=r.display_name, icon=r.icon,
        ))
        n += 1
    db.commit()
    return {"copied": n, "to_season": payload.to_season}
