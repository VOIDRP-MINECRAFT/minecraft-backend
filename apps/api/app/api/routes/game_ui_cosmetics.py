"""In-game WebGUI cosmetics (Figura) — a shop, identical for everyone.

Every authenticated player sees the same catalogue of enabled cosmetics, can buy one with Void
Coins (or claim it if free / already granted), and equip/unequip it. Equipping sets the player's
Figura equipped list and pushes a WS EVENT so every client renders it. There are NO management
actions here — uploading/editing/granting lives in the site admin panel (routes/admin_cosmetics.py)
and the in-game `/vrgs cosmetic` command (plugin_router below). See docs/figura_backend_spec.md.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.api.routes.figura import _offline_uuid
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.figura import FiguraEquipped
from apps.api.app.models.figura_cosmetic import FiguraCosmetic, FiguraCosmeticOwned
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.services.figura_ws import hub

router = APIRouter(prefix="/game-ui/cosmetics", tags=["game-ui", "cosmetics"])
plugin_router = APIRouter(prefix="/game-sync/cosmetics", tags=["cosmetics"])

COSMETIC_OWNER = "00000000-0000-0000-0000-0000000000c0"


def _uuid_of(player: PlayerAccount) -> str:
    return _offline_uuid(player.minecraft_nickname)


def _equipped_slugs(db: Session, owner_uuid: str) -> set[str]:
    eq = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == owner_uuid)).scalar_one_or_none()
    if eq is None:
        return set()
    return {e["id"] for e in (eq.equipped or []) if e.get("owner") == COSMETIC_OWNER}


def _apply_equip_slot(db: Session, uuid: str, cat: FiguraCosmetic) -> None:
    """Per-slot equip: keep other slots + the player's own avatar, replace this slot's cosmetic."""
    row = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == uuid)).scalar_one_or_none()
    current = list(row.equipped or []) if row else []
    cur_slugs = [e["id"] for e in current if e.get("owner") == COSMETIC_OWNER and e.get("id")]
    slot_of = dict(db.execute(
        select(FiguraCosmetic.slug, FiguraCosmetic.slot).where(FiguraCosmetic.slug.in_(cur_slugs))
    ).all()) if cur_slugs else {}
    kept = []
    for e in current:
        if e.get("owner") != COSMETIC_OWNER:
            kept.append(e)
        elif slot_of.get(e.get("id")) not in (cat.slot, None):
            kept.append(e)
    kept.append({"owner": COSMETIC_OWNER, "id": cat.slug})
    if row is None:
        db.add(FiguraEquipped(owner_uuid=uuid, equipped=kept, version=1))
    else:
        row.equipped = kept
        row.version = int(row.version) + 1


def _apply_unequip(db: Session, uuid: str, slug: str | None = None) -> None:
    row = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == uuid)).scalar_one_or_none()
    if row is None:
        return
    row.equipped = [e for e in (row.equipped or []) if e.get("id") != slug] if slug else []
    row.version = int(row.version) + 1


# ── schemas ──
class CosmeticOut(BaseModel):
    slug: str
    name: str
    slot: str
    price: int
    owned: bool
    equipped: bool
    preview_url: str | None = None
    featured: bool = False
    is_new: bool = False


class CosmeticsResponse(BaseModel):
    void_coins: int
    catalog: list[CosmeticOut]


class SlugRequest(BaseModel):
    slug: str


# ── player: catalogue / buy / equip ──
@router.get("", response_model=CosmeticsResponse)
def list_cosmetics(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CosmeticsResponse:
    owned = {
        r for (r,) in db.execute(
            select(FiguraCosmeticOwned.cosmetic_slug).where(FiguraCosmeticOwned.user_id == player.user_id)
        ).all()
    }
    equipped = _equipped_slugs(db, _uuid_of(player))
    catalog = db.execute(
        select(FiguraCosmetic).order_by(FiguraCosmetic.sort_order, FiguraCosmetic.name)
    ).scalars().all()
    # players see enabled cosmetics, plus anything they already own (even if later disabled)
    visible = [c for c in catalog if bool(c.enabled) or c.slug in owned]
    from datetime import datetime, timedelta, timezone
    new_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return CosmeticsResponse(
        void_coins=int(player.void_coins or 0),
        catalog=[
            CosmeticOut(
                slug=c.slug, name=c.name, slot=c.slot, price=int(c.price_void_coins),
                owned=(c.slug in owned), equipped=(c.slug in equipped),
                preview_url=c.preview_url, featured=bool(c.featured),
                is_new=(c.created_at is not None and c.created_at > new_cutoff),
            )
            for c in visible
        ],
    )


@router.post("/buy")
def buy_cosmetic(
    req: SlugRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    cat = db.execute(
        select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug, FiguraCosmetic.enabled.is_(True))
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Косметика не найдена.")
    already = db.execute(
        select(FiguraCosmeticOwned).where(
            FiguraCosmeticOwned.user_id == player.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
        )
    ).scalar_one_or_none()
    if already is not None:
        return {"ok": True, "already_owned": True, "new_void_coins": int(player.void_coins or 0)}
    price = int(cat.price_void_coins)
    new_balance = int(player.void_coins or 0)
    if price > 0:
        row = db.execute(
            update(PlayerAccount)
            .where(PlayerAccount.user_id == player.user_id, PlayerAccount.void_coins >= price)
            .values(void_coins=PlayerAccount.void_coins - price)
            .returning(PlayerAccount.void_coins)
        ).first()
        if row is None:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Недостаточно Void Coin — нужно {price}.")
        new_balance = int(row[0])
    db.add(FiguraCosmeticOwned(user_id=player.user_id, cosmetic_slug=req.slug))
    db.commit()
    return {"ok": True, "new_void_coins": new_balance}


class GiftRequest(BaseModel):
    nickname: str
    slug: str


@router.post("/gift")
def gift_cosmetic(
    req: GiftRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Buy a cosmetic FOR another player: buyer pays, target receives ownership + a toast."""
    cat = db.execute(
        select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug, FiguraCosmetic.enabled.is_(True))
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Косметика не найдена.")
    target = db.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == req.nickname.strip().lower())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Игрок «{req.nickname}» не найден.")
    if target.user_id == player.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Себе — используйте «Купить».")
    if db.execute(select(FiguraCosmeticOwned).where(
        FiguraCosmeticOwned.user_id == target.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
    )).scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="У игрока уже есть эта косметика.")
    price = int(cat.price_void_coins)
    new_balance = int(player.void_coins or 0)
    if price > 0:
        row = db.execute(
            update(PlayerAccount)
            .where(PlayerAccount.user_id == player.user_id, PlayerAccount.void_coins >= price)
            .values(void_coins=PlayerAccount.void_coins - price)
            .returning(PlayerAccount.void_coins)
        ).first()
        if row is None:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Недостаточно Void Coin — нужно {price}.")
        new_balance = int(row[0])
    db.add(FiguraCosmeticOwned(user_id=target.user_id, cosmetic_slug=req.slug))
    # toast the lucky recipient
    try:
        from apps.api.app.models.game_server import GameServer
        from apps.api.app.services.notification_service import NotificationService
        sid = db.execute(select(GameServer.id).where(GameServer.is_default.is_(True))).scalar_one_or_none()
        if sid is not None:
            NotificationService(db, sid).create(
                user_id=target.user_id, type="cosmetic",
                title="Вам подарили косметику!", body=f"«{cat.name}» от {player.minecraft_nickname} — наденьте в Косметике.",
                icon="user", accent="violet",
                action_type="route", action_payload="game-ui-cosmetics", action_label="Открыть",
            )
    except Exception:  # noqa: BLE001
        pass
    db.commit()
    return {"ok": True, "new_void_coins": new_balance, "nickname": target.minecraft_nickname, "name": cat.name}


@router.post("/equip")
async def equip_cosmetic(
    req: SlugRequest,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Косметика не найдена.")
    owned = db.execute(
        select(FiguraCosmeticOwned).where(
            FiguraCosmeticOwned.user_id == player.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
        )
    ).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Косметика не куплена.")
    uuid = _uuid_of(player)
    _apply_equip_slot(db, uuid, cat)
    db.commit()
    await hub.notify_event(uuid)
    return {"ok": True, "equipped": req.slug}


@router.post("/unequip")
async def unequip_cosmetic(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    slug: str | None = None,
) -> dict:
    """Unequip one cosmetic (?slug=) or all (no slug)."""
    uuid = _uuid_of(player)
    _apply_unequip(db, uuid, slug)
    db.commit()
    await hub.notify_event(uuid)
    return {"ok": True}


# ── plugin-facing (game-auth): in-game admin grant + catalog list ──
@plugin_router.get("")
def plugin_list_cosmetics(
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    rows = db.execute(select(FiguraCosmetic).order_by(FiguraCosmetic.name)).scalars().all()
    return {"cosmetics": [{"slug": c.slug, "name": c.name, "slot": c.slot,
                           "price": int(c.price_void_coins), "enabled": bool(c.enabled)} for c in rows]}


@plugin_router.get("/owned")
def plugin_owned_cosmetics(
    nickname: str,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """A player's owned cosmetics + equipped state — for the in-game /cosmetics GUI."""
    target = db.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == nickname.strip().lower())
    ).scalar_one_or_none()
    if target is None:
        return {"owned": []}
    slugs = [r for (r,) in db.execute(
        select(FiguraCosmeticOwned.cosmetic_slug).where(FiguraCosmeticOwned.user_id == target.user_id)
    ).all()]
    if not slugs:
        return {"owned": []}
    cats = {c.slug: c for c in db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug.in_(slugs))).scalars().all()}
    equipped = _equipped_slugs(db, _offline_uuid(target.minecraft_nickname))
    out = []
    for slug in slugs:
        c = cats.get(slug)
        out.append({"slug": slug, "name": (c.name if c else slug), "slot": (c.slot if c else "full"),
                    "equipped": slug in equipped})
    return {"owned": out}


class PluginEquipRequest(BaseModel):
    nickname: str
    slug: str | None = None


@plugin_router.post("/equip")
async def plugin_equip_cosmetic(
    req: PluginEquipRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    target = db.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == req.nickname.strip().lower())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="player not found")
    uuid = _offline_uuid(target.minecraft_nickname)
    if not req.slug:                                        # unequip all
        _apply_unequip(db, uuid, None)
        db.commit()
        await hub.notify_event(uuid)
        return {"ok": True, "equipped": None}
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cosmetic not found")
    owned = db.execute(select(FiguraCosmeticOwned).where(
        FiguraCosmeticOwned.user_id == target.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
    )).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not owned")
    # toggle: if already equipped, take it off; else put it on
    already = req.slug in _equipped_slugs(db, uuid)
    if already:
        _apply_unequip(db, uuid, req.slug)
    else:
        _apply_equip_slot(db, uuid, cat)
    db.commit()
    await hub.notify_event(uuid)
    return {"ok": True, "equipped": None if already else req.slug}


class PluginGrantRequest(BaseModel):
    nickname: str
    slug: str


@plugin_router.post("/grant")
def plugin_grant_cosmetic(
    req: PluginGrantRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cosmetic not found")
    target = db.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == req.nickname.strip().lower())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="player not found")
    exists = db.execute(
        select(FiguraCosmeticOwned).where(
            FiguraCosmeticOwned.user_id == target.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(FiguraCosmeticOwned(user_id=target.user_id, cosmetic_slug=req.slug))
        try:
            from apps.api.app.services.notification_service import NotificationService
            NotificationService(db, server.id).create(
                user_id=target.user_id, type="cosmetic",
                title="Выдана косметика", body=f"«{cat.name}» — наденьте в WebGUI → Косметика.",
                icon="user", accent="violet",
                action_type="route", action_payload="game-ui-cosmetics", action_label="Открыть",
            )
        except Exception:  # noqa: BLE001
            pass
        db.commit()
    return {"ok": True, "nickname": target.minecraft_nickname, "slug": req.slug,
            "name": cat.name, "already_owned": exists is not None}
