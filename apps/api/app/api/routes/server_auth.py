from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import localize_player_access_error, translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_skin import PlayerSkin
from apps.api.app.schemas.server_auth import (
    LegacyLoginRequest,
    LegacyLoginResponse,
    PlayerAccessRequest,
    PlayerAccessResponse,
    PlayerSkinResponse,
)
from apps.api.app.services.legacy_auth_service import LegacyAuthService, LegacyAuthValidationError
from apps.api.app.services.redis_cache_service import RedisCacheService
from apps.api.app.services.server_player_access_service import ServerPlayerAccessService
from apps.api.app.utils.normalization import normalize_minecraft_nickname

router = APIRouter(
    prefix="/server/auth",
    tags=["server-auth"],
    dependencies=[Depends(require_game_auth_secret)],
)


def get_legacy_auth_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> LegacyAuthService:
    return LegacyAuthService(session=session)


@router.post("/legacy-login", response_model=LegacyLoginResponse)
def legacy_login(
    payload: LegacyLoginRequest,
    service: Annotated[LegacyAuthService, Depends(get_legacy_auth_service)],
) -> LegacyLoginResponse:
    try:
        result = service.legacy_login(
            player_name=payload.player_name,
            password=payload.password,
        )
    except LegacyAuthValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=translate_user_message(str(exc))) from exc

    return LegacyLoginResponse(
        user_id=result.user_id,
        minecraft_nickname=result.minecraft_nickname,
        legacy_auth_enabled=result.legacy_auth_enabled,
        email_verified=result.email_verified,
    )


@router.post("/player-access", response_model=PlayerAccessResponse)
def player_access(
    payload: PlayerAccessRequest,
    _: None = Depends(require_game_auth_secret),
    session: Session = Depends(get_db_session),
) -> PlayerAccessResponse:
    service = ServerPlayerAccessService(session)
    result = service.get_player_access(player_name=payload.player_name)

    return PlayerAccessResponse(
        player_exists=result.player_exists,
        user_active=result.user_active,
        legacy_auth_enabled=result.legacy_auth_enabled,
        must_use_launcher=result.must_use_launcher,
        minecraft_nickname=result.minecraft_nickname,
        error=localize_player_access_error(result.error),
    )


@router.get("/player-skin/{player_name}", response_model=PlayerSkinResponse)
def player_skin(
    player_name: str,
    _: None = Depends(require_game_auth_secret),
    session: Session = Depends(get_db_session),
) -> PlayerSkinResponse:
    _, normalized = normalize_minecraft_nickname(player_name)
    cache = RedisCacheService()
    cached = cache.get_json(f"player_skin:{normalized}")
    if cached is not None:
        return PlayerSkinResponse(**cached)

    player_account = session.execute(
        select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == normalized)
    ).scalar_one_or_none()

    if player_account is None:
        payload = PlayerSkinResponse(
            player_exists=False,
            has_skin=False,
            model_variant="classic",
            skin_url=None,
            head_preview_url=None,
            body_preview_url=None,
            width=None,
            height=None,
            sha256=None,
            updated_at=None,
        )
        cache.set_json(f"player_skin:{normalized}", payload.model_dump(mode="json"), ttl_seconds=20)
        return payload

    skin = session.execute(
        select(PlayerSkin).where(PlayerSkin.user_id == player_account.user_id)
    ).scalar_one_or_none()

    payload = PlayerSkinResponse(
        player_exists=True,
        has_skin=skin is not None,
        model_variant=(skin.model_variant if skin else "classic"),
        skin_url=(skin.original_url if skin else None),
        head_preview_url=(skin.head_preview_url if skin else None),
        body_preview_url=(skin.body_preview_url if skin else None),
        width=(skin.width if skin else None),
        height=(skin.height if skin else None),
        sha256=(skin.sha256 if skin else None),
        updated_at=(skin.updated_at.isoformat() if skin and skin.updated_at else None),
    )
    cache.set_json(f"player_skin:{normalized}", payload.model_dump(mode="json"), ttl_seconds=20)
    return payload
