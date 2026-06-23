from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import localize_response_message, translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.user import User
from apps.api.app.schemas.referral import (
    ReferralCodePreviewResponse,
    ReferralDashboardResponse,
    RegenerateReferralCodeResponse,
)
from apps.api.app.services.referral_service import ReferralNotFoundError, ReferralService

router = APIRouter(prefix="/referrals", tags=["referrals"])


def get_referral_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> ReferralService:
    return ReferralService(session=session)


@router.get("/me", response_model=ReferralDashboardResponse)
def get_my_referrals(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReferralService, Depends(get_referral_service)],
) -> ReferralDashboardResponse:
    return service.get_dashboard(current_user=current_user)


@router.post("/me/regenerate-code", response_model=RegenerateReferralCodeResponse)
def regenerate_my_referral_code(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReferralService, Depends(get_referral_service)],
) -> RegenerateReferralCodeResponse:
    return localize_response_message(service.regenerate_code(current_user=current_user))


@router.get("/{code}/preview", response_model=ReferralCodePreviewResponse)
def preview_referral_code(
    code: str,
    service: Annotated[ReferralService, Depends(get_referral_service)],
) -> ReferralCodePreviewResponse:
    try:
        return service.preview_code(code)
    except ReferralNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
