"""Site-admin CRUD for Figura cosmetics (global catalogue).

Behind the site admin panel (JWT + `figura.cosmetics.manage`). The admin uploads an exported
Figura avatar blob (gzip-NBT) as a catalogue cosmetic, edits/deletes it, and can grant one to a
player by nick. The in-game shop (routes/game_ui_cosmetics.py) and the `/vrgs cosmetic` command
consume this catalogue. A cosmetic's blob is stored under the fixed system UUID COSMETIC_OWNER.
"""
from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.api.routes.figura import _offline_uuid
from apps.api.app.config import get_settings
from apps.api.app.core.audit import record_audit
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_permission
from apps.api.app.models.figura import FiguraAvatar, FiguraEquipped
from apps.api.app.models.figura_cosmetic import FiguraCosmetic, FiguraCosmeticOwned
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user import User
from apps.api.app.services.figura_ws import hub

router = APIRouter(
    prefix="/admin/cosmetics",
    tags=["admin", "cosmetics"],
    dependencies=[Depends(require_permission("figura.cosmetics.manage"))],
)

COSMETIC_OWNER = "00000000-0000-0000-0000-0000000000c0"
SLOTS = {"full", "head", "body", "wings", "accessory"}
MAX_MODEL_BYTES = 2 * 1024 * 1024


def _slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "-", name.strip().lower())[:48].strip("-")


def _notify_granted(db: Session, user_id, cosmetic_name: str) -> None:
    """Best-effort in-game toast (HUD notification) when a cosmetic is granted."""
    try:
        from apps.api.app.models.game_server import GameServer
        from apps.api.app.services.notification_service import NotificationService
        server_id = db.execute(select(GameServer.id).where(GameServer.is_default.is_(True))).scalar_one_or_none()
        if server_id is None:
            return
        NotificationService(db, server_id).create(
            user_id=user_id, type="cosmetic",
            title="Выдана косметика", body=f"«{cosmetic_name}» — наденьте в WebGUI → Косметика.",
            icon="user", accent="violet",
            action_type="route", action_payload="game-ui-cosmetics", action_label="Открыть",
        )
    except Exception:  # noqa: BLE001 — never break the grant
        pass


class CosmeticOut(BaseModel):
    slug: str
    name: str
    slot: str
    price: int
    enabled: bool
    size_bytes: int
    owned_count: int
    preview_url: str | None = None
    sort_order: int = 0
    featured: bool = False


def _out(cat: FiguraCosmetic, size: int, owned: int) -> CosmeticOut:
    return CosmeticOut(
        slug=cat.slug, name=cat.name, slot=cat.slot, price=int(cat.price_void_coins),
        enabled=bool(cat.enabled), size_bytes=int(size), owned_count=int(owned),
        preview_url=cat.preview_url, sort_order=int(cat.sort_order or 0), featured=bool(cat.featured),
    )


@router.get("", response_model=list[CosmeticOut])
def list_cosmetics(db: Annotated[Session, Depends(get_db_session)]) -> list[CosmeticOut]:
    cats = db.execute(select(FiguraCosmetic).order_by(FiguraCosmetic.sort_order, FiguraCosmetic.name)).scalars().all()
    sizes = {
        aid: sz for aid, sz in db.execute(
            select(FiguraAvatar.avatar_id, FiguraAvatar.size_bytes).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER)
        ).all()
    }
    counts = {
        slug: n for slug, n in db.execute(
            select(FiguraCosmeticOwned.cosmetic_slug, func.count()).group_by(FiguraCosmeticOwned.cosmetic_slug)
        ).all()
    }
    return [_out(c, sizes.get(c.slug, 0), counts.get(c.slug, 0)) for c in cats]


@router.post("/upload", response_model=CosmeticOut, status_code=status.HTTP_201_CREATED)
async def upload_cosmetic(
    db: Annotated[Session, Depends(get_db_session)],
    file: UploadFile = File(...),
    name: str = Form(...),
    slot: str = Form("full"),
    price: int = Form(0),
) -> CosmeticOut:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл.")
    if len(data) > MAX_MODEL_BYTES:
        raise HTTPException(status_code=400, detail=f"Файл больше {MAX_MODEL_BYTES // (1024*1024)} МБ.")
    if data[:2] != b"\x1f\x8b":
        raise HTTPException(status_code=400, detail="Не похоже на аватар Figura (ожидается gzip). Экспортируй модель из Figura.")
    sha = hashlib.sha256(data).hexdigest()
    slug = _slugify(name) or f"cosmetic-{sha[:8]}"   # Cyrillic-only names → hash-based slug
    if slot not in SLOTS:
        slot = "full"
    av = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none()
    if av is None:
        db.add(FiguraAvatar(owner_uuid=COSMETIC_OWNER, avatar_id=slug, data=data,
                            sha256=sha, size_bytes=len(data), is_cosmetic=True))
    else:
        av.data, av.sha256, av.size_bytes, av.is_cosmetic = data, sha, len(data), True
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    if cat is None:
        cat = FiguraCosmetic(slug=slug, name=name.strip()[:64], slot=slot, price_void_coins=max(0, int(price)), enabled=True)
        db.add(cat)
    else:
        cat.name, cat.slot, cat.price_void_coins = name.strip()[:64], slot, max(0, int(price))
    db.commit()
    return _out(cat, len(data), 0)


# ── promote an avatar a player loaded in-game (valid Figura NBT) into the catalog ──
class UploadInfo(BaseModel):
    avatar_id: str
    size_bytes: int


@router.get("/uploads", response_model=list[UploadInfo])
def list_player_uploads(
    nickname: Annotated[str, Query(min_length=1, max_length=32)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[UploadInfo]:
    """Avatars a player loaded via the Figura wardrobe (stored under their own UUID, valid NBT).
    These are the only blobs that can be promoted into the catalogue."""
    uuid = _offline_uuid(nickname.strip())
    rows = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == uuid).order_by(FiguraAvatar.updated_at.desc())
    ).scalars().all()
    return [UploadInfo(avatar_id=a.avatar_id, size_bytes=int(a.size_bytes)) for a in rows]


class PromoteRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=32)
    source_avatar_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=64)
    slot: str = "full"
    price: int = Field(default=0, ge=0)


@router.post("/promote", response_model=CosmeticOut, status_code=status.HTTP_201_CREATED)
def promote_cosmetic(req: PromoteRequest, db: Annotated[Session, Depends(get_db_session)]) -> CosmeticOut:
    src = db.execute(
        select(FiguraAvatar).where(
            FiguraAvatar.owner_uuid == _offline_uuid(req.nickname.strip()),
            FiguraAvatar.avatar_id == req.source_avatar_id,
        )
    ).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="Аватар не найден. Загрузи модель в Figura в игре.")
    slug = _slugify(req.name) or f"cosmetic-{src.sha256[:8]}"
    slot = req.slot if req.slot in SLOTS else "full"
    av = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none()
    if av is None:
        db.add(FiguraAvatar(owner_uuid=COSMETIC_OWNER, avatar_id=slug, data=src.data,
                            sha256=src.sha256, size_bytes=src.size_bytes, is_cosmetic=True))
    else:
        av.data, av.sha256, av.size_bytes, av.is_cosmetic = src.data, src.sha256, src.size_bytes, True
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    if cat is None:
        cat = FiguraCosmetic(slug=slug, name=req.name.strip()[:64], slot=slot, price_void_coins=max(0, int(req.price)), enabled=True)
        db.add(cat)
    else:
        cat.name, cat.slot, cat.price_void_coins = req.name.strip()[:64], slot, max(0, int(req.price))
    db.commit()
    return _out(cat, int(src.size_bytes), 0)


class PatchRequest(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    slot: str | None = None
    price: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    featured: bool | None = None


@router.patch("/{slug}", response_model=CosmeticOut)
def patch_cosmetic(
    slug: str,
    req: PatchRequest,
    db: Annotated[Session, Depends(get_db_session)],
) -> CosmeticOut:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="Косметика не найдена.")
    if req.name is not None:
        cat.name = req.name.strip()[:64]
    if req.slot is not None and req.slot in SLOTS:
        cat.slot = req.slot
    if req.price is not None:
        cat.price_void_coins = int(req.price)
    if req.enabled is not None:
        cat.enabled = bool(req.enabled)
    if req.sort_order is not None:
        cat.sort_order = int(req.sort_order)
    if req.featured is not None:
        cat.featured = bool(req.featured)
    db.commit()
    size = db.execute(
        select(FiguraAvatar.size_bytes).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none() or 0
    owned = db.execute(
        select(func.count()).select_from(FiguraCosmeticOwned).where(FiguraCosmeticOwned.cosmetic_slug == slug)
    ).scalar_one()
    return _out(cat, size, owned)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cosmetic(
    slug: str,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
) -> None:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    name = cat.name if cat else slug
    if cat is not None:
        db.delete(cat)
    av = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none()
    if av is not None:
        db.delete(av)
    db.execute(FiguraCosmeticOwned.__table__.delete().where(FiguraCosmeticOwned.cosmetic_slug == slug))
    db.commit()
    record_audit(db, category="cosmetics", action="delete", actor=admin,
                 target_type="cosmetic", target_id=slug, target_label=name)


class GrantRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=32)
    slug: str = Field(..., min_length=1, max_length=64)


@router.post("/grant")
def grant_cosmetic(
    req: GrantRequest,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == req.slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="Косметика не найдена.")
    target = db.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == req.nickname.strip().lower())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"Игрок «{req.nickname}» не найден.")
    exists = db.execute(
        select(FiguraCosmeticOwned).where(
            FiguraCosmeticOwned.user_id == target.user_id, FiguraCosmeticOwned.cosmetic_slug == req.slug
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(FiguraCosmeticOwned(user_id=target.user_id, cosmetic_slug=req.slug))
        _notify_granted(db, target.user_id, cat.name)
        db.commit()
        record_audit(db, category="cosmetics", action="grant", actor=admin,
                     target_type="player", target_id=target.minecraft_nickname,
                     target_label=cat.name, meta={"slug": req.slug})
    return {"ok": True, "nickname": target.minecraft_nickname, "slug": req.slug,
            "name": cat.name, "already_owned": exists is not None}


# ── preview image (what the player sees in the shop) ──
_MAX_PREVIEW_BYTES = 6 * 1024 * 1024
_PREVIEW_MAX = 512   # px, longest side; aspect preserved, alpha kept


@router.post("/{slug}/preview", response_model=CosmeticOut)
async def upload_preview(
    slug: str,
    db: Annotated[Session, Depends(get_db_session)],
    file: UploadFile = File(...),
) -> CosmeticOut:
    cat = db.execute(select(FiguraCosmetic).where(FiguraCosmetic.slug == slug)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="Косметика не найдена.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл.")
    if len(raw) > _MAX_PREVIEW_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 6 МБ.")
    try:
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if (img.format or "").upper() not in {"PNG", "JPEG", "JPG", "WEBP"}:
                raise HTTPException(status_code=400, detail="Только PNG, JPEG или WEBP.")
            working = img.convert("RGBA")   # keep transparency for rendered avatars
            if max(working.width, working.height) > _PREVIEW_MAX:
                ratio = _PREVIEW_MAX / max(working.width, working.height)
                working = working.resize(
                    (max(1, int(working.width * ratio)), max(1, int(working.height * ratio))),
                    Image.Resampling.LANCZOS,
                )
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Файл не является корректным изображением.")

    settings = get_settings()
    rel_dir = Path("cosmetics")
    filename = f"{slug}-{uuid4().hex[:8]}.webp"
    abs_dir = Path(settings.media_storage_root) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    working.save(abs_dir / filename, format="WEBP", quality=90, method=4)
    cat.preview_url = f"{settings.media_public_base_url}/{(rel_dir / filename).as_posix()}"
    db.commit()

    size = db.execute(
        select(FiguraAvatar.size_bytes).where(FiguraAvatar.owner_uuid == COSMETIC_OWNER, FiguraAvatar.avatar_id == slug)
    ).scalar_one_or_none() or 0
    owned = db.execute(
        select(func.count()).select_from(FiguraCosmeticOwned).where(FiguraCosmeticOwned.cosmetic_slug == slug)
    ).scalar_one()
    return _out(cat, size, owned)


# ── player-owned cosmetics: view + revoke ──
class OwnedOut(BaseModel):
    slug: str
    name: str
    slot: str
    equipped: bool


@router.get("/player", response_model=list[OwnedOut])
def list_player_cosmetics(
    nickname: Annotated[str, Query(min_length=1, max_length=32)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[OwnedOut]:
    target = db.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == nickname.strip().lower())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"Игрок «{nickname}» не найден.")
    slugs = [r for (r,) in db.execute(
        select(FiguraCosmeticOwned.cosmetic_slug).where(FiguraCosmeticOwned.user_id == target.user_id)
    ).all()]
    if not slugs:
        return []
    cats = {c.slug: c for c in db.execute(
        select(FiguraCosmetic).where(FiguraCosmetic.slug.in_(slugs))
    ).scalars().all()}
    eq = db.execute(
        select(FiguraEquipped).where(FiguraEquipped.owner_uuid == _offline_uuid(target.minecraft_nickname))
    ).scalar_one_or_none()
    equipped = {e["id"] for e in (eq.equipped or [])} if eq else set()
    out = []
    for slug in slugs:
        c = cats.get(slug)
        out.append(OwnedOut(slug=slug, name=(c.name if c else slug), slot=(c.slot if c else "—"),
                            equipped=(slug in equipped)))
    return out


class RevokeRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=32)
    slug: str = Field(..., min_length=1, max_length=64)


@router.post("/revoke")
async def revoke_cosmetic(
    req: RevokeRequest,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[User, Depends(get_current_staff_user)],
) -> dict:
    target = db.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == req.nickname.strip().lower())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"Игрок «{req.nickname}» не найден.")
    db.execute(
        FiguraCosmeticOwned.__table__.delete().where(
            FiguraCosmeticOwned.user_id == target.user_id,
            FiguraCosmeticOwned.cosmetic_slug == req.slug,
        )
    )
    # if the player had it equipped, take it off + tell every client to re-render
    uuid = _offline_uuid(target.minecraft_nickname)
    eq = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == uuid)).scalar_one_or_none()
    unequipped = False
    if eq is not None and any(e.get("id") == req.slug for e in (eq.equipped or [])):
        eq.equipped = [e for e in (eq.equipped or []) if e.get("id") != req.slug]
        eq.version = int(eq.version) + 1
        unequipped = True
    db.commit()
    if unequipped:
        await hub.notify_event(uuid)
    record_audit(db, category="cosmetics", action="revoke", actor=admin,
                 target_type="player", target_id=target.minecraft_nickname,
                 target_label=req.slug, meta={"unequipped": unequipped})
    return {"ok": True, "nickname": target.minecraft_nickname, "slug": req.slug, "unequipped": unequipped}


# ── who owns a given cosmetic ──
class OwnerOut(BaseModel):
    nickname: str
    equipped: bool


@router.get("/{slug}/owners", response_model=list[OwnerOut])
def list_cosmetic_owners(slug: str, db: Annotated[Session, Depends(get_db_session)]) -> list[OwnerOut]:
    rows = db.execute(
        select(PlayerAccount.minecraft_nickname)
        .join(FiguraCosmeticOwned, FiguraCosmeticOwned.user_id == PlayerAccount.user_id)
        .where(FiguraCosmeticOwned.cosmetic_slug == slug)
        .order_by(PlayerAccount.minecraft_nickname)
    ).all()
    out = []
    for (nick,) in rows:
        eq = db.execute(
            select(FiguraEquipped).where(FiguraEquipped.owner_uuid == _offline_uuid(nick))
        ).scalar_one_or_none()
        equipped = bool(eq and any(e.get("id") == slug for e in (eq.equipped or [])))
        out.append(OwnerOut(nickname=nick, equipped=equipped))
    return out
