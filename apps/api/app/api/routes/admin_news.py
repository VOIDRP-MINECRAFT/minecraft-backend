from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import (
    caller_permissions,
    get_current_staff_user,
    require_any_permission,
)
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.news import NewsPost
from apps.api.app.models.user import User
from apps.api.app.repositories.game_server_repository import GameServerRepository
from apps.api.app.schemas.news import (
    NewsAdminListResponse,
    NewsBroadcastRequest,
    NewsBroadcastResult,
    NewsPostAdmin,
    NewsPostCreate,
    NewsPostUpdate,
)
from apps.api.app.services.news_service import NewsService

_NEWS_KEYS = (
    "news.updates.view", "news.updates.manage",
    "news.media.view", "news.media.manage",
)

router = APIRouter(
    prefix="/admin/news",
    tags=["admin", "news"],
    # Any news permission lets the tab load; per-endpoint checks the exact key.
    dependencies=[Depends(require_any_permission(*_NEWS_KEYS))],
)

_VALID_CATEGORIES = {"update", "media"}


def _perm_key(category: str, action: str) -> str:
    seg = "updates" if category == "update" else "media"
    return f"news.{seg}.{action}"


def _require_cat(perms: set[str], category: str, action: str) -> None:
    if _perm_key(category, action) not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {_perm_key(category, action)}",
        )


_ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Covers are normalized to a 16:6 banner so they always fully fill the card and
# the news-page banner. Uploads below the minimum are rejected (would be blurry).
_COVER_TARGET = (1600, 600)  # 16:6
_COVER_MIN_WIDTH = 1000
_COVER_MIN_HEIGHT = 375


@router.post(
    "/upload-image",
    dependencies=[Depends(require_any_permission("news.updates.manage", "news.media.manage"))],
)
async def upload_cover_image(file: UploadFile = File(...)) -> dict:
    """Upload a news cover image → returns a public URL. Center-cropped to a
    1600×600 (16:6) banner and saved as WebP."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="file too large (max 8 MB)")
    try:
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if (img.format or "").upper() not in _ALLOWED_IMAGE_FORMATS:
                raise HTTPException(status_code=400, detail="Только PNG, JPEG или WEBP.")
            if img.width < _COVER_MIN_WIDTH or img.height < _COVER_MIN_HEIGHT:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Изображение слишком маленькое ({img.width}×{img.height}). "
                        f"Нужно минимум {_COVER_MIN_WIDTH}×{_COVER_MIN_HEIGHT}. "
                        "Рекомендуется 1600×600 (соотношение 16:6)."
                    ),
                )
            working = img.convert("RGB")
            target_ratio = _COVER_TARGET[0] / _COVER_TARGET[1]
            w, h = working.width, working.height
            if w / h > target_ratio:
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                working = working.crop((left, 0, left + new_w, h))
            else:
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                working = working.crop((0, top, w, top + new_h))
            working = working.resize(_COVER_TARGET, Image.Resampling.LANCZOS)
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Файл не является корректным изображением.")

    settings = get_settings()
    rel_dir = Path("news")
    filename = f"cover-{uuid4().hex}.webp"
    abs_dir = Path(settings.media_storage_root) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    working.save(abs_dir / filename, format="WEBP", quality=88, method=4)
    return {"url": f"{settings.media_public_base_url}/{(rel_dir / filename).as_posix()}"}


def _server(session: Session, server_id: UUID) -> GameServer:
    server = GameServerRepository(session).get_by_id(server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return server


def _admin(post: NewsPost) -> NewsPostAdmin:
    return NewsPostAdmin(
        id=str(post.id),
        category=post.category,
        title=post.title,
        slug=post.slug,
        summary=post.summary,
        body=post.body,
        cover_image_url=post.cover_image_url,
        published_at=post.published_at,
        author_name=post.author_name,
        server_id=str(post.server_id),
        is_published=post.is_published,
        posted_telegram=post.posted_telegram,
        posted_discord=post.posted_discord,
        created_at=post.created_at,
    )


def _channel_flags(server: GameServer, category: str) -> dict:
    ch = server.channels_for(category)
    return {"tg": bool(ch["telegram"]), "dc": bool(ch["discord"])}


@router.get("/servers")
def list_news_servers(session: Annotated[Session, Depends(get_db_session)]) -> list[dict]:
    """Server dropdown for the news editor (any news perm). Channel config is
    reduced to per-category booleans — no secrets."""
    servers = GameServerRepository(session).list_all()
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "is_default": s.is_default,
            "channels": {
                "update": _channel_flags(s, "update"),
                "media": _channel_flags(s, "media"),
            },
        }
        for s in servers
    ]


def _validate_category(category: str) -> str:
    if category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    return category


@router.get("", response_model=NewsAdminListResponse)
def list_news(
    session: Annotated[Session, Depends(get_db_session)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    server_id: Annotated[UUID, Query(...)],
    category: Annotated[str, Query(...)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NewsAdminListResponse:
    _validate_category(category)
    _require_cat(perms, category, "view")
    server = _server(session, server_id)
    items, total = NewsService(session, server).list_admin(limit, offset, category=category)
    return NewsAdminListResponse(items=[_admin(p) for p in items], total=total)


@router.get("/{post_id}", response_model=NewsPostAdmin)
def get_news(
    post_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    server_id: Annotated[UUID, Query(...)],
) -> NewsPostAdmin:
    server = _server(session, server_id)
    post = NewsService(session, server).get_by_id(post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News post not found")
    _require_cat(perms, post.category, "view")
    return _admin(post)


@router.post("", response_model=NewsPostAdmin, status_code=status.HTTP_201_CREATED)
def create_news(
    payload: NewsPostCreate,
    session: Annotated[Session, Depends(get_db_session)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    admin: Annotated[User, Depends(get_current_staff_user)],
    server_id: Annotated[UUID, Query(...)],
) -> NewsPostAdmin:
    _require_cat(perms, payload.category, "manage")
    server = _server(session, server_id)
    service = NewsService(session, server)
    post = service.create(
        category=payload.category,
        title=payload.title,
        summary=payload.summary,
        body=payload.body,
        cover_image_url=payload.cover_image_url,
        is_published=payload.is_published,
        author=admin,
    )
    if post.is_published and (payload.post_telegram or payload.post_discord):
        service.broadcast(post, to_telegram=payload.post_telegram, to_discord=payload.post_discord)
    session.commit()
    session.refresh(post)
    return _admin(post)


@router.patch("/{post_id}", response_model=NewsPostAdmin)
def update_news(
    post_id: UUID,
    payload: NewsPostUpdate,
    session: Annotated[Session, Depends(get_db_session)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    server_id: Annotated[UUID, Query(...)],
) -> NewsPostAdmin:
    server = _server(session, server_id)
    service = NewsService(session, server)
    post = service.get_by_id(post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News post not found")
    _require_cat(perms, post.category, "manage")
    service.update(post, payload.model_dump(exclude_unset=True))
    session.commit()
    session.refresh(post)
    return _admin(post)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(
    post_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    server_id: Annotated[UUID, Query(...)],
) -> None:
    server = _server(session, server_id)
    service = NewsService(session, server)
    post = service.get_by_id(post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News post not found")
    _require_cat(perms, post.category, "manage")
    service.delete(post)
    session.commit()


@router.post("/{post_id}/broadcast", response_model=NewsBroadcastResult)
def broadcast_news(
    post_id: UUID,
    payload: NewsBroadcastRequest,
    session: Annotated[Session, Depends(get_db_session)],
    perms: Annotated[set[str], Depends(caller_permissions)],
    server_id: Annotated[UUID, Query(...)],
) -> NewsBroadcastResult:
    server = _server(session, server_id)
    service = NewsService(session, server)
    post = service.get_by_id(post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News post not found")
    _require_cat(perms, post.category, "manage")
    res = service.broadcast(post, to_telegram=payload.post_telegram, to_discord=payload.post_discord)
    session.commit()
    detail = None
    if payload.post_telegram and res.get("telegram_ok") is False:
        detail = "Telegram не настроен или отправка не удалась (проверь bot token и chat_id)."
    if payload.post_discord and res.get("discord_ok") is False:
        detail = (detail + " " if detail else "") + "Discord webhook не настроен или недоступен."
    return NewsBroadcastResult(
        telegram_ok=res.get("telegram_ok"), discord_ok=res.get("discord_ok"), detail=detail
    )
