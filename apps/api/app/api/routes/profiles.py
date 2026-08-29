from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user, get_optional_current_user
from apps.api.app.models.user import User
from apps.api.app.schemas.profile import (
    DeleteProfileAssetResponse,
    ProfileAssetUploadResponse,
    PublicProfileRead,
    UpdatePublicProfileRequest,
)
from apps.api.app.services.media_service import MediaValidationError, ProfileMediaService
from apps.api.app.services.public_profile_service import (
    PublicProfileConflictError,
    PublicProfileNotFoundError,
    PublicProfileService,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


def get_profile_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicProfileService:
    return PublicProfileService(session=session)


def get_profile_media_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> ProfileMediaService:
    return ProfileMediaService(session=session)


@router.get("/me", response_model=PublicProfileRead)
def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PublicProfileService, Depends(get_profile_service)],
) -> PublicProfileRead:
    return service.get_me(current_user)


@router.patch("/me", response_model=PublicProfileRead)
def update_my_profile(
    payload: UpdatePublicProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PublicProfileService, Depends(get_profile_service)],
) -> PublicProfileRead:
    try:
        return service.update_me(current_user, payload)
    except PublicProfileConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=translate_user_message(str(exc)),
        ) from exc


@router.get("/{slug}", response_model=PublicProfileRead)
def get_public_profile(
    slug: str,
    viewer: Annotated[User | None, Depends(get_optional_current_user)],
    service: Annotated[PublicProfileService, Depends(get_profile_service)],
) -> PublicProfileRead:
    try:
        return service.get_by_slug(slug, viewer=viewer)
    except PublicProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate_user_message(str(exc)),
        ) from exc


@router.get("/{slug}/game")
def get_public_profile_game_stats(
    slug: str,
    viewer: Annotated[User | None, Depends(get_optional_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
):
    """Public game stats + achievements for a profile (default server), for the shareable page."""
    from sqlalchemy import func, select

    from apps.api.app.api.routes.game_ui_home import (
        Achievement,
        HomeStats,
        _compute_achievements,
    )
    from apps.api.app.models.game_server import GameServer
    from apps.api.app.models.nation_member import NationMember
    from apps.api.app.models.player_account import PlayerAccount
    from apps.api.app.models.player_public_profile import PlayerPublicProfile
    from apps.api.app.models.player_stat_cache import PlayerStatCache

    profile = session.execute(
        select(PlayerPublicProfile)
        .join(PlayerPublicProfile.user)
        .join(User.player_account)
        .where(PlayerPublicProfile.slug == slug)
    ).scalar_one_or_none()
    if profile is None:
        profile = session.execute(
            select(PlayerPublicProfile)
            .join(PlayerPublicProfile.user)
            .join(User.player_account)
            .where(func.lower(PlayerAccount.minecraft_nickname) == slug.lower())
        ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль не найден.")
    if not profile.is_public and (viewer is None or viewer.id != profile.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль не найден.")

    account = session.execute(
        select(PlayerAccount).where(PlayerAccount.user_id == profile.user_id)
    ).scalar_one_or_none()
    nick = account.minecraft_nickname if account else None
    if not nick:
        return {"nickname": None, "stats": HomeStats().model_dump(), "achievements": []}

    server = session.execute(
        select(GameServer).where(GameServer.is_default.is_(True))
    ).scalar_one_or_none()

    stats = HomeStats()
    if server is not None:
        stat = session.execute(
            select(PlayerStatCache).where(
                PlayerStatCache.server_id == server.id,
                PlayerStatCache.minecraft_nickname_normalized == nick.lower(),
            )
        ).scalar_one_or_none()
        if stat is not None:
            stats = HomeStats(
                playtime_minutes=stat.total_playtime_minutes,
                balance=float(stat.current_balance or 0),
                pvp_kills=stat.pvp_kills,
                mob_kills=stat.mob_kills,
                deaths=stat.deaths,
                best_kill_streak=stat.best_kill_streak,
                blocks_placed=stat.blocks_placed,
                blocks_broken=stat.blocks_broken,
                completed_quests=stat.completed_quests,
            )

    has_nation = False
    if server is not None:
        has_nation = session.execute(
            select(NationMember.id).where(
                NationMember.user_id == profile.user_id, NationMember.server_id == server.id
            )
        ).scalar_one_or_none() is not None

    achievements = _compute_achievements(stats, has_nation)
    return {
        "nickname": nick,
        "stats": stats.model_dump(),
        "achievements": [a.model_dump() for a in achievements],
    }


@router.post("/me/avatar", response_model=ProfileAssetUploadResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    media_service: Annotated[ProfileMediaService, Depends(get_profile_media_service)] = None,
    profile_service: Annotated[PublicProfileService, Depends(get_profile_service)] = None,
) -> ProfileAssetUploadResponse:
    try:
        await media_service.save_profile_asset(current_user=current_user, slot="avatar", upload=file)
    except MediaValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=translate_user_message(str(exc)),
        ) from exc

    return ProfileAssetUploadResponse(
        message="Аватар успешно загружен.",
        profile=profile_service.get_me(current_user),
    )


@router.delete("/me/avatar", response_model=DeleteProfileAssetResponse)
def delete_avatar(
    current_user: Annotated[User, Depends(get_current_user)],
    media_service: Annotated[ProfileMediaService, Depends(get_profile_media_service)],
    profile_service: Annotated[PublicProfileService, Depends(get_profile_service)],
) -> DeleteProfileAssetResponse:
    media_service.remove_profile_asset(current_user=current_user, slot="avatar")
    return DeleteProfileAssetResponse(
        message="Аватар удалён.",
        profile=profile_service.get_me(current_user),
    )


@router.post("/me/banner", response_model=ProfileAssetUploadResponse)
async def upload_banner(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    media_service: Annotated[ProfileMediaService, Depends(get_profile_media_service)] = None,
    profile_service: Annotated[PublicProfileService, Depends(get_profile_service)] = None,
) -> ProfileAssetUploadResponse:
    try:
        await media_service.save_profile_asset(current_user=current_user, slot="banner", upload=file)
    except MediaValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=translate_user_message(str(exc)),
        ) from exc

    return ProfileAssetUploadResponse(
        message="Баннер успешно загружен.",
        profile=profile_service.get_me(current_user),
    )


@router.delete("/me/banner", response_model=DeleteProfileAssetResponse)
def delete_banner(
    current_user: Annotated[User, Depends(get_current_user)],
    media_service: Annotated[ProfileMediaService, Depends(get_profile_media_service)],
    profile_service: Annotated[PublicProfileService, Depends(get_profile_service)],
) -> DeleteProfileAssetResponse:
    media_service.remove_profile_asset(current_user=current_user, slot="banner")
    return DeleteProfileAssetResponse(
        message="Баннер удалён.",
        profile=profile_service.get_me(current_user),
    )


@router.post("/me/background", response_model=ProfileAssetUploadResponse)
async def upload_background(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    media_service: Annotated[ProfileMediaService, Depends(get_profile_media_service)] = None,
    profile_service: Annotated[PublicProfileService, Depends(get_profile_service)] = None,
) -> ProfileAssetUploadResponse:
    try:
        await media_service.save_profile_asset(current_user=current_user, slot="background", upload=file)
    except MediaValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=translate_user_message(str(exc)),
        ) from exc

    return ProfileAssetUploadResponse(
        message="Фон успешно загружен.",
        profile=profile_service.get_me(current_user),
    )


@router.delete("/me/background", response_model=DeleteProfileAssetResponse)
def delete_background(
    current_user: Annotated[User, Depends(get_current_user)],
    media_service: Annotated[ProfileMediaService, Depends(get_profile_media_service)],
    profile_service: Annotated[PublicProfileService, Depends(get_profile_service)],
) -> DeleteProfileAssetResponse:
    media_service.remove_profile_asset(current_user=current_user, slot="background")
    return DeleteProfileAssetResponse(
        message="Фон удалён.",
        profile=profile_service.get_me(current_user),
    )
