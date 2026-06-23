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
