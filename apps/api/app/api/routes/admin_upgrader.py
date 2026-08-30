"""Admin CRUD for the Void Upgrader reward pool (per server)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.economy_market import EconomyMarketItem
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.void_upgrader import VoidUpgraderReward
from apps.api.app.services.void_upgrader_service import COINS_PER_VC, MAX_MULTIPLIER, RTP

router = APIRouter(
    prefix="/admin/upgrader",
    tags=["admin", "upgrader"],
    dependencies=[Depends(require_permission("upgrader.view"))],
)

_TIERS = {"common", "rare", "epic", "legendary"}


def _tier_for(vc: int) -> str:
    if vc >= 250:
        return "legendary"
    if vc >= 80:
        return "epic"
    if vc >= 25:
        return "rare"
    return "common"


class RewardOut(BaseModel):
    id: str
    item_key: str
    display_name: str
    image_url: str | None
    vc_value: int
    amount: int
    tier: str
    give_command: str | None
    enabled: bool


class RewardCreate(BaseModel):
    item_key: str = Field(..., min_length=3, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=128)
    vc_value: int = Field(..., ge=1, le=1_000_000_000)
    amount: int = Field(default=1, ge=1, le=6400)
    tier: str | None = None
    give_command: str | None = Field(default=None, max_length=256)
    enabled: bool = True


class RewardUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    vc_value: int | None = Field(default=None, ge=1, le=1_000_000_000)
    amount: int | None = Field(default=None, ge=1, le=6400)
    tier: str | None = None
    give_command: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None


class ConfigOut(BaseModel):
    rtp: float
    coins_per_vc: int
    max_multiplier: float


def _out(r: VoidUpgraderReward) -> RewardOut:
    return RewardOut(
        id=str(r.id), item_key=r.item_key, display_name=r.display_name, image_url=r.image_url,
        vc_value=int(r.vc_value), amount=int(r.amount or 1), tier=r.tier,
        give_command=r.give_command, enabled=bool(r.enabled),
    )


@router.get("/config", response_model=ConfigOut)
def get_config() -> ConfigOut:
    return ConfigOut(rtp=RTP, coins_per_vc=COINS_PER_VC, max_multiplier=MAX_MULTIPLIER)


@router.get("/rewards", response_model=list[RewardOut])
def list_rewards(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> list[RewardOut]:
    rows = db.execute(
        select(VoidUpgraderReward)
        .where(VoidUpgraderReward.server_id == server.id)
        .order_by(VoidUpgraderReward.vc_value)
    ).scalars().all()
    return [_out(r) for r in rows]


@router.post("/rewards", response_model=RewardOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("upgrader.manage"))])
def create_reward(
    payload: RewardCreate,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> RewardOut:
    item_key = payload.item_key.strip().lower()
    exists = db.execute(
        select(VoidUpgraderReward).where(
            VoidUpgraderReward.server_id == server.id,
            VoidUpgraderReward.item_key == item_key,
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Этот предмет уже в пуле.")
    tier = payload.tier if payload.tier in _TIERS else _tier_for(payload.vc_value)
    row = VoidUpgraderReward(
        server_id=server.id, item_key=item_key, display_name=payload.display_name.strip(),
        vc_value=payload.vc_value, amount=payload.amount, tier=tier,
        give_command=(payload.give_command or None), enabled=payload.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


def _get(db: Session, server_id: UUID, reward_id: UUID) -> VoidUpgraderReward:
    row = db.execute(
        select(VoidUpgraderReward).where(
            VoidUpgraderReward.id == reward_id,
            VoidUpgraderReward.server_id == server_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Награда не найдена.")
    return row


@router.patch("/rewards/{reward_id}", response_model=RewardOut,
              dependencies=[Depends(require_permission("upgrader.manage"))])
def update_reward(
    reward_id: UUID,
    payload: RewardUpdate,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> RewardOut:
    row = _get(db, server.id, reward_id)
    data = payload.model_dump(exclude_unset=True)
    if "display_name" in data and data["display_name"]:
        row.display_name = data["display_name"].strip()
    if "vc_value" in data and data["vc_value"]:
        row.vc_value = data["vc_value"]
    if "amount" in data and data["amount"]:
        row.amount = data["amount"]
    if "tier" in data:
        row.tier = data["tier"] if data["tier"] in _TIERS else _tier_for(int(row.vc_value))
    if "give_command" in data:
        row.give_command = data["give_command"] or None
    if "enabled" in data and data["enabled"] is not None:
        row.enabled = bool(data["enabled"])
    db.commit()
    db.refresh(row)
    return _out(row)


class ImportResult(BaseModel):
    added: int
    skipped: int


@router.post("/import-market", response_model=ImportResult,
             dependencies=[Depends(require_permission("upgrader.manage"))])
def import_from_market(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> ImportResult:
    """Pull enabled market items into the pool as DISABLED drafts (for review).

    vc_value = market price / COINS_PER_VC (min 10). Items already in the pool are skipped,
    so re-running only adds newly-listed market items.
    """
    existing = set(db.execute(
        select(VoidUpgraderReward.item_key).where(VoidUpgraderReward.server_id == server.id)
    ).scalars().all())
    market = db.execute(
        select(EconomyMarketItem).where(
            EconomyMarketItem.server_id == server.id,
            EconomyMarketItem.enabled.is_(True),
        )
    ).scalars().all()

    added = skipped = 0
    for m in market:
        item_key = str(m.material or "").strip().lower()
        if not item_key or ":" not in item_key or item_key in existing:
            skipped += 1
            continue
        price = float(m.current_buy_price or m.base_buy_price or 0)
        vc = max(10, round(price / COINS_PER_VC))
        display = m.display_name or item_key.split(":")[-1].replace("_", " ").title()
        db.add(VoidUpgraderReward(
            server_id=server.id, item_key=item_key, display_name=display,
            vc_value=vc, amount=1, tier=_tier_for(vc), enabled=False,  # draft: review before enabling
        ))
        existing.add(item_key)
        added += 1
    db.commit()
    return ImportResult(added=added, skipped=skipped)


@router.delete("/rewards/{reward_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("upgrader.manage"))])
def delete_reward(
    reward_id: UUID,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> None:
    row = _get(db, server.id, reward_id)
    db.delete(row)
    db.commit()
