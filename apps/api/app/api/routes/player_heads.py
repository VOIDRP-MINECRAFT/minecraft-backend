from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_skin import PlayerSkin
from apps.api.app.services.redis_cache_service import RedisCacheService
from apps.api.app.utils.normalization import normalize_minecraft_nickname

router = APIRouter(prefix="/public", tags=["public"])

_CACHE_TTL = 60


@router.get(
    "/player-head/{nickname}",
    summary="Redirect to player head preview image (no auth required)",
    responses={302: {"description": "Redirect to head preview URL"}, 404: {"description": "Player has no skin"}},
)
def get_player_head(
    nickname: str,
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    """
    Returns a 302 redirect to the player's head preview PNG.
    Use directly as <img src="/api/v1/public/player-head/{nickname}"> with an onerror fallback.
    Returns 404 when the player has no skin in the database.

    Reuses the player_skin:{normalized} Redis cache populated by the server-auth endpoint.
    Falls back to a dedicated cache key player_head:{normalized} with 60-second TTL.
    """
    _, normalized = normalize_minecraft_nickname(nickname)
    cache = RedisCacheService()

    # Reuse the full skin cache if it's already warm (server-auth endpoint populates it)
    cached_full = cache.get_json(f"player_skin:{normalized}")
    if cached_full is not None:
        url = cached_full.get("head_preview_url")
        if url:
            return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Dedicated lightweight cache for this endpoint
    cached_entry = cache.get_json(f"player_head:{normalized}")
    if cached_entry is not None:
        url = cached_entry.get("u")
        if not url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)

    # DB lookup
    player_account = session.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == normalized)
    ).scalar_one_or_none()

    if player_account is None:
        cache.set_json(f"player_head:{normalized}", {"u": ""}, ttl_seconds=_CACHE_TTL)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    skin = session.execute(
        select(PlayerSkin).where(PlayerSkin.user_id == player_account.user_id)
    ).scalar_one_or_none()

    if skin is None or not skin.head_preview_url:
        cache.set_json(f"player_head:{normalized}", {"u": ""}, ttl_seconds=_CACHE_TTL)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    cache.set_json(f"player_head:{normalized}", {"u": skin.head_preview_url}, ttl_seconds=_CACHE_TTL)
    return RedirectResponse(url=skin.head_preview_url, status_code=status.HTTP_302_FOUND)
