from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import localize_response_message, translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.user import User
from apps.api.app.schemas.social import FollowActionResponse, SocialListResponse
from apps.api.app.services.social_service import SocialNotFoundError, SocialService, SocialValidationError

router = APIRouter(prefix="/social", tags=["social"])


def get_social_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> SocialService:
    return SocialService(session=session)


@router.post("/follow/{slug}", response_model=FollowActionResponse)
def follow_profile(
    slug: str,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SocialService, Depends(get_social_service)],
) -> FollowActionResponse:
    try:
        return localize_response_message(service.follow(current_user=current_user, target_slug=slug))
    except SocialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except SocialValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.delete("/follow/{slug}", response_model=FollowActionResponse)
def unfollow_profile(
    slug: str,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SocialService, Depends(get_social_service)],
) -> FollowActionResponse:
    try:
        return localize_response_message(service.unfollow(current_user=current_user, target_slug=slug))
    except SocialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.get("/me/followers", response_model=SocialListResponse)
def get_my_followers(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SocialService, Depends(get_social_service)],
) -> SocialListResponse:
    return service.list_followers(current_user=current_user)


@router.get("/me/following", response_model=SocialListResponse)
def get_my_following(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SocialService, Depends(get_social_service)],
) -> SocialListResponse:
    return service.list_following(current_user=current_user)


@router.get("/me/friends", response_model=SocialListResponse)
def get_my_friends(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SocialService, Depends(get_social_service)],
) -> SocialListResponse:
    return service.list_friends(current_user=current_user)
