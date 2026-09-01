"""In-game WebGUI cosmetics (Figura) — catalog, ownership, purchase with Void Coins, equip.

Admin-only for now (the tab is hidden for non-admins). A cosmetic is a Figura avatar owned by
a fixed system UUID; a catalog row (FiguraCosmetic) gives it a name/slot/price. Players buy a
cosmetic → own it → equip it, which sets their Figura equipped list and pushes a WS EVENT so
every client renders it. See docs/figura_backend_spec.md.
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.api.routes.figura import _offline_uuid
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.figura import FiguraAvatar, FiguraEquipped
from apps.api.app.models.figura_cosmetic import FiguraCosmetic, FiguraCosmeticOwned
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user import User
from apps.api.app.services.figura_ws import hub

router = APIRouter(prefix="/game-ui/cosmetics", tags=["game-ui", "cosmetics"])

COSMETIC_OWNER = "00000000-0000-0000-0000-0000000000c0"


class Ctx:
    def __init__(self, player: PlayerAccount, user: User) -> None:
        self.player = player
        self.user = user
        self.uuid = _offline_uuid(player.minecraft_nickname)


def _ctx(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Ctx:
    user = db.execute(select(User).where(User.id == player.user_id)).scalar_one_or_none()
    if user is None or not user.is_admin:   # admin-only for now
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для администратора.")
    return Ctx(player, user)


# ── schemas ──
class CosmeticOut(BaseModel):
    slug: str
    name: str
    slot: str
    price: int
    enabled: bool
    owned: bool
    equipped: bool


class MyAvatarOut(BaseModel):
    id: str
    size_bytes: int


class CosmeticsResponse(BaseModel):
    is_admin: bool = True
    void_coins: int
    catalog: list[CosmeticOut]
    my_avatars: list[MyAvatarOut]


def _equipped_slugs(db: Session, owner_uuid: str) -> set[str]:
    eq = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == owner_uuid)).scalar_one_or_none()
    if eq is None:
        return set()
    return {e["id"] for e in (eq.equipped or []) if e.get("owner") == COSMETIC_OWNER}


@router.get("", response_model=CosmeticsResponse)
def list_cosmetics(
    ctx: Annotated[Ctx, Depends(_ctx)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CosmeticsResponse:
    catalog = db.execute(select(FiguraCosmetic).order_by(FiguraCosmetic.name)).scalars().all()
    owned = {
        r for (r,) in db.execute(
            select(FiguraCosmeticOwned.cosmetic_slug).where(FiguraCosmeticOwned.user_id == ctx.player.user_id)
        ).all()
    }
    equipped = _equipped_slugs(db, ctx.uuid)
    mine = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == ctx.uuid).order_by(FiguraAvatar.updated_at.desc())
    ).scalars().all()
    return CosmeticsResponse(
        void_coins=int(ctx.player.void_coins or 0),
        catalog=[
            CosmeticOut(
                slug=c.slug, name=c.name, slot=c.slot, price=int(c.price_void_coins), enabled=bool(c.enabled),
                owned=(c.slug in owned), equipped=(c.slug in equipped),
            )
            for c in catalog
        ],
        my_avatars=[MyAvatarOut(id=a.avatar_id, size_bytes=int(a.size_bytes)) for a in mine],
    )


# ── admin: build the catalog from uploaded Figura avatars ──
class PromoteRequest(BaseModel):
    source_avatar_id: str
    name: str
    slot: str = "full"
    price: int = Field(default=0, ge=0)


@router.post("/promote", response_model=CosmeticOut)
def promote(
    req: PromoteRequest,
    ctx: Annotated[Ctx, Depends(_ctx)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CosmeticOut:
    src = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == ctx.uuid, FiguraAvatar.avatar_id == req.source_avatar_id)
    ).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аватар не найден. Загрузи его в игре через Figura.")
    slug = re.sub(r"[^A-Za-z0-9_\-]", "-", req.name.strip().lower())[:48].strip("-") or req.source_avatar_id.lower()
    # store the avatar blob under COSMETIC_OWNER
    av = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none()
    if av is None:
        db.add(FiguraAvatar(owner_uuid=COSMETIC_OWNER, avatar_id=slug, data=src.data,
                            sha256=src.sha256, size_bytes=src.size_bytes, is_cosmetic=True))
    else:
        av.data, av.sha256, av.size_bytes, av.is_cosmetic = src.data, src.sha256, src.size_bytes, True
    # catalog row
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    if cat is None:
        cat = FiguraCosmetic(slug=slug, name=req.name.strip()[:64], slot=req.slot, price_void_coins=req.price, enabled=True)
        db.add(cat)
    else:
        cat.name, cat.slot, cat.price_void_coins = req.name.strip()[:64], req.slot, req.price
    db.commit()
    return CosmeticOut(slug=slug, name=cat.name, slot=cat.slot, price=int(cat.price_void_coins),
                       enabled=True, owned=False, equipped=False)


class PatchRequest(BaseModel):
    name: str | None = None
    slot: str | None = None
    price: int | None = Field(default=None, ge=0)
    enabled: bool | None = None


@router.patch("/{slug}", response_model=CosmeticOut)
def patch_cosmetic(
    slug: str,
    req: PatchRequest,
    ctx: Annotated[Ctx, Depends(_ctx)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CosmeticOut:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Косметика не найдена.")
    if req.name is not None:
        cat.name = req.name.strip()[:64]
    if req.slot is not None:
        cat.slot = req.slot
    if req.price is not None:
        cat.price_void_coins = req.price
    if req.enabled is not None:
        cat.enabled = req.enabled
    db.commit()
    return CosmeticOut(slug=cat.slug, name=cat.name, slot=cat.slot, price=int(cat.price_void_coins),
                       enabled=bool(cat.enabled), owned=False, equipped=False)


@router.delete("/{slug}")
def delete_cosmetic(
    slug: str,
    ctx: Annotated[Ctx, Depends(_ctx)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    if cat is not None:
        db.delete(cat)
    av = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none()
    if av is not None:
        db.delete(av)
    db.execute(FiguraCosmeticOwned.__table__.delete().where(FiguraCosmeticOwned.cosmetic_slug == slug))
    db.commit()
    return {"ok": True}


# ── player: buy / equip (economy ready; still admin-gated for now) ──
class SlugRequest(BaseModel):
    slug: str


@router.post("/buy")
def buy_cosmetic(
    req: SlugRequest,
    ctx: Annotated[Ctx, Depends(_ctx)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    cat = db.execute(
        select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug, FiguraCosmetic.enabled.is_(True))
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Косметика не найдена.")
    already = db.execute(
        select(FiguraCosmeticOwned).where(
            FiguraCosmeticOwned.user_id == ctx.player.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
        )
    ).scalar_one_or_none()
    if already is not None:
        return {"ok": True, "already_owned": True, "new_void_coins": int(ctx.player.void_coins or 0)}
    price = int(cat.price_void_coins)
    new_balance = int(ctx.player.void_coins or 0)
    if price > 0:
        row = db.execute(
            update(PlayerAccount)
            .where(PlayerAccount.user_id == ctx.player.user_id, PlayerAccount.void_coins >= price)
            .values(void_coins=PlayerAccount.void_coins - price)
            .returning(PlayerAccount.void_coins)
        ).first()
        if row is None:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Недостаточно Void Coin — нужно {price}.")
        new_balance = int(row[0])
    db.add(FiguraCosmeticOwned(user_id=ctx.player.user_id, cosmetic_slug=req.slug))
    db.commit()
    return {"ok": True, "new_void_coins": new_balance}


@router.post("/equip")
async def equip_cosmetic(
    req: SlugRequest,
    ctx: Annotated[Ctx, Depends(_ctx)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Косметика не найдена.")
    owned = db.execute(
        select(FiguraCosmeticOwned).where(
            FiguraCosmeticOwned.user_id == ctx.player.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
        )
    ).scalar_one_or_none()
    if owned is None and not ctx.user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Косметика не куплена.")
    equipped = [{"owner": COSMETIC_OWNER, "id": req.slug}]
    row = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == ctx.uuid)).scalar_one_or_none()
    if row is None:
        db.add(FiguraEquipped(owner_uuid=ctx.uuid, equipped=equipped, version=1))
    else:
        row.equipped = equipped
        row.version = int(row.version) + 1
    db.commit()
    await hub.notify_event(ctx.uuid)
    return {"ok": True, "equipped": req.slug}


@router.post("/unequip")
async def unequip_cosmetic(
    ctx: Annotated[Ctx, Depends(_ctx)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    row = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == ctx.uuid)).scalar_one_or_none()
    if row is not None:
        row.equipped = []
        row.version = int(row.version) + 1
        db.commit()
        await hub.notify_event(ctx.uuid)
    return {"ok": True}
