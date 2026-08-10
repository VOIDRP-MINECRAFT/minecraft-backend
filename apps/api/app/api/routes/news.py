from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.news import NewsListResponse, NewsPostPublic
from apps.api.app.services.news_service import NewsService

router = APIRouter(prefix="/news", tags=["news"])


def _to_public(post) -> NewsPostPublic:
    return NewsPostPublic(
        id=str(post.id),
        category=post.category,
        title=post.title,
        slug=post.slug,
        summary=post.summary,
        body=post.body,
        cover_image_url=post.cover_image_url,
        published_at=post.published_at,
        author_name=post.author_name,
    )


@router.get("", response_model=NewsListResponse)
def list_news(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
    category: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NewsListResponse:
    cat = category if category in ("update", "media") else None
    items, total = NewsService(session, server).list_public(limit, offset, category=cat)
    return NewsListResponse(items=[_to_public(p) for p in items], total=total)


@router.get("/{slug}", response_model=NewsPostPublic)
def get_news(
    slug: str,
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NewsPostPublic:
    post = NewsService(session, server).get_public_by_slug(slug)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News post not found")
    return _to_public(post)
