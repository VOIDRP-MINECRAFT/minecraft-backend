"""In-game WebGUI cosmetics (Figura avatars). Admin-only for now — the admin picks a
cosmetic and wears it; later this becomes the player-facing wardrobe + Void Coin shop.

A cosmetic is a Figura avatar owned by a fixed system UUID; "wearing" it sets the player's
Figura equipped list to point at it, and the Figura backend WS pushes an EVENT so every
client re-fetches and renders it. See docs/figura_backend_spec.md.
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.api.routes.figura import _offline_uuid
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.figura import FiguraAvatar, FiguraEquipped
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user import User
from apps.api.app.services.figura_ws import hub

router = APIRouter(prefix="/game-ui/cosmetics", tags=["game-ui", "cosmetics"])

COSMETIC_OWNER = "00000000-0000-0000-0000-0000000000c0"   # system owner for all cosmetics


def _require_admin(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> tuple[PlayerAccount, str]:
    user = db.execute(select(User).where(User.id == player.user_id)).scalar_one_or_none()
    if user is None or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для администратора.")
    return player, _offline_uuid(player.minecraft_nickname)


class CosmeticOut(BaseModel):
    id: str            # avatar_id under COSMETIC_OWNER
    name: str
    size_bytes: int


class MyAvatarOut(BaseModel):
    id: str
    size_bytes: int


class CosmeticsResponse(BaseModel):
    is_admin: bool = True
    cosmetics: list[CosmeticOut]
    my_avatars: list[MyAvatarOut]
    equipped: list[str]   # cosmetic ids currently worn by the caller


def _equipped_ids(db: Session, owner_uuid: str) -> list[str]:
    eq = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == owner_uuid)).scalar_one_or_none()
    if eq is None:
        return []
    return [e["id"] for e in (eq.equipped or []) if e.get("owner") == COSMETIC_OWNER]


@router.get("", response_model=CosmeticsResponse)
def list_cosmetics(
    ctx: Annotated[tuple[PlayerAccount, str], Depends(_require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CosmeticsResponse:
    _, my_uuid = ctx
    cosmetics = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.is_cosmetic.is_(True))
        .order_by(FiguraAvatar.avatar_id)
    ).scalars().all()
    mine = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == my_uuid).order_by(FiguraAvatar.updated_at.desc())
    ).scalars().all()
    return CosmeticsResponse(
        cosmetics=[CosmeticOut(id=c.avatar_id, name=c.avatar_id, size_bytes=int(c.size_bytes)) for c in cosmetics],
        my_avatars=[MyAvatarOut(id=a.avatar_id, size_bytes=int(a.size_bytes)) for a in mine],
        equipped=_equipped_ids(db, my_uuid),
    )


class PromoteRequest(BaseModel):
    source_avatar_id: str
    name: str


@router.post("/promote", response_model=CosmeticOut)
def promote_to_cosmetic(
    req: PromoteRequest,
    ctx: Annotated[tuple[PlayerAccount, str], Depends(_require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CosmeticOut:
    """Turn one of the admin's own uploaded Figura avatars into a shared cosmetic."""
    _, my_uuid = ctx
    src = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == my_uuid, FiguraAvatar.avatar_id == req.source_avatar_id)
    ).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аватар не найден. Сначала загрузи его в игре через Figura.")
    slug = re.sub(r"[^A-Za-z0-9_\- ]", "", req.name).strip()[:48] or req.source_avatar_id
    existing = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none()
    if existing is None:
        db.add(FiguraAvatar(owner_uuid=COSMETIC_OWNER, avatar_id=slug, data=src.data,
                            sha256=src.sha256, size_bytes=src.size_bytes, is_cosmetic=True))
    else:
        existing.data, existing.sha256, existing.size_bytes, existing.is_cosmetic = src.data, src.sha256, src.size_bytes, True
    db.commit()
    return CosmeticOut(id=slug, name=slug, size_bytes=int(src.size_bytes))


class EquipRequest(BaseModel):
    cosmetic_id: str


@router.post("/equip")
async def equip_cosmetic(
    req: EquipRequest,
    ctx: Annotated[tuple[PlayerAccount, str], Depends(_require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    _, my_uuid = ctx
    cosmetic = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == req.cosmetic_id)
    ).scalar_one_or_none()
    if cosmetic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Косметика не найдена.")
    equipped = [{"owner": COSMETIC_OWNER, "id": req.cosmetic_id}]
    row = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == my_uuid)).scalar_one_or_none()
    if row is None:
        db.add(FiguraEquipped(owner_uuid=my_uuid, equipped=equipped, version=1))
    else:
        row.equipped = equipped
        row.version = int(row.version) + 1
    db.commit()
    await hub.notify_event(my_uuid)
    return {"ok": True, "equipped": req.cosmetic_id}


@router.post("/unequip")
async def unequip_cosmetic(
    ctx: Annotated[tuple[PlayerAccount, str], Depends(_require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    _, my_uuid = ctx
    row = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == my_uuid)).scalar_one_or_none()
    if row is not None:
        row.equipped = []
        row.version = int(row.version) + 1
        db.commit()
        await hub.notify_event(my_uuid)
    return {"ok": True}


@router.delete("/{cosmetic_id}")
def delete_cosmetic(
    cosmetic_id: str,
    ctx: Annotated[tuple[PlayerAccount, str], Depends(_require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    c = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == cosmetic_id)
    ).scalar_one_or_none()
    if c is not None:
        db.delete(c)
        db.commit()
    return {"ok": True}
