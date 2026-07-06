from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from apps.api.app.core.user_messages import localize_response_message, translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user, get_optional_current_user
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.schemas.nation import (
    NationActionResponse,
    NationCreateRequest,
    NationDisbandResponse,
    NationJoinActionResponse,
    NationJoinRequestCreate,
    NationListResponse,
    NationMemberPrefixUpdateRequest,
    NationMemberRoleUpdateRequest,
    NationRead,
    NationTransferLeadershipRequest,
    NationUpdateRequest,
)
from apps.api.app.schemas.nation_activity import NationActivityLogListResponse
from apps.api.app.services.nation_activity_service import NationActivityNotFoundError, NationActivityService
from apps.api.app.services.nation_media_service import NationMediaService, NationMediaValidationError
from apps.api.app.services.nation_service import (
    NationConflictError,
    NationNotFoundError,
    NationPermissionError,
    NationService,
    NationValidationError,
)

router = APIRouter(prefix="/nations", tags=["nations"])


def get_nation_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NationService:
    return NationService(session=session, server_id=server.id)


def get_nation_media_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NationMediaService:
    return NationMediaService(session=session, server_id=server.id)


def get_nation_activity_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NationActivityService:
    return NationActivityService(session=session, server_id=server.id)


@router.get("", response_model=NationListResponse)
def list_nations(viewer: Annotated[User | None, Depends(get_optional_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationListResponse:
    return service.list_public(viewer=viewer)


@router.get("/me", response_model=NationRead | None)
def get_my_nation(current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationRead | None:
    return service.get_my_nation(current_user)


@router.get("/me/activity", response_model=NationActivityLogListResponse)
def get_my_nation_activity(current_user: Annotated[User, Depends(get_current_user)], nation_service: Annotated[NationService, Depends(get_nation_service)], activity_service: Annotated[NationActivityService, Depends(get_nation_activity_service)]) -> NationActivityLogListResponse:
    nation = nation_service._find_nation_for_user(current_user.id)
    if nation is None:
        return NationActivityLogListResponse(total=0, items=[])
    return activity_service.list_for_nation_id(nation.id)


@router.get("/{slug}", response_model=NationRead)
def get_nation_by_slug(slug: str, viewer: Annotated[User | None, Depends(get_optional_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationRead:
    try:
        return service.get_by_slug(slug, viewer=viewer)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.get("/{slug}/activity", response_model=NationActivityLogListResponse)
def get_nation_activity(slug: str, activity_service: Annotated[NationActivityService, Depends(get_nation_activity_service)]) -> NationActivityLogListResponse:
    try:
        return activity_service.list_for_slug(slug)
    except NationActivityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.post("", response_model=NationRead)
def create_nation(payload: NationCreateRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationRead:
    try:
        return service.create(current_user, payload)
    except NationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=translate_user_message(str(exc))) from exc
    except NationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.patch("/me", response_model=NationRead)
def update_my_nation(payload: NationUpdateRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationRead:
    try:
        return service.update_my_nation(current_user, payload)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=translate_user_message(str(exc))) from exc
    except NationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc


@router.post("/me/leave", response_model=NationActionResponse)
def leave_my_nation(current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationActionResponse:
    try:
        return localize_response_message(service.leave_my_nation(current_user))
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc
    except NationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.delete("/me", response_model=NationDisbandResponse)
def disband_my_nation(current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationDisbandResponse:
    try:
        return localize_response_message(service.disband_my_nation(current_user))
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc


@router.post("/{slug}/join", response_model=NationJoinActionResponse)
def create_join_request(slug: str, payload: NationJoinRequestCreate, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationJoinActionResponse:
    try:
        return localize_response_message(service.join(current_user, slug, payload))
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=translate_user_message(str(exc))) from exc
    except NationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.post("/{slug}/requests/{request_id}/approve", response_model=NationRead)
def approve_join_request(slug: str, request_id: UUID, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationRead:
    try:
        return service.approve_request(current_user, slug, request_id)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc


@router.post("/{slug}/requests/{request_id}/reject", response_model=NationRead)
def reject_join_request(slug: str, request_id: UUID, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationRead:
    try:
        return service.reject_request(current_user, slug, request_id)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc


@router.patch("/{slug}/members/{target_user_id}/role", response_model=NationActionResponse)
def update_member_role(slug: str, target_user_id: UUID, payload: NationMemberRoleUpdateRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationActionResponse:
    try:
        return localize_response_message(service.update_member_role(current_user=current_user, slug=slug, target_user_id=target_user_id, payload=payload))
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc
    except NationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.patch("/{slug}/members/{target_user_id}/prefix", response_model=NationActionResponse)
def update_member_prefix(slug: str, target_user_id: UUID, payload: NationMemberPrefixUpdateRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationActionResponse:
    try:
        return localize_response_message(service.update_member_prefix(current_user=current_user, slug=slug, target_user_id=target_user_id, payload=payload))
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc


@router.delete("/{slug}/members/{target_user_id}", response_model=NationActionResponse)
def remove_member(slug: str, target_user_id: UUID, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationActionResponse:
    try:
        return localize_response_message(service.remove_member(current_user=current_user, slug=slug, target_user_id=target_user_id))
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc
    except NationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.post("/{slug}/transfer-leadership", response_model=NationActionResponse)
def transfer_leadership(slug: str, payload: NationTransferLeadershipRequest, current_user: Annotated[User, Depends(get_current_user)], service: Annotated[NationService, Depends(get_nation_service)]) -> NationActionResponse:
    try:
        return localize_response_message(service.transfer_leadership(current_user=current_user, slug=slug, payload=payload))
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc
    except NationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc


@router.post("/me/assets/{slot}", response_model=NationRead)
async def upload_nation_asset(slot: str, file: UploadFile = File(...), current_user: Annotated[User, Depends(get_current_user)] = None, media_service: Annotated[NationMediaService, Depends(get_nation_media_service)] = None) -> NationRead:
    try:
        nation = await media_service.save_nation_asset(current_user, slot, file)
        return NationService(media_service.session, media_service.server_id).get_by_slug(nation.slug, viewer=current_user)
    except NationMediaValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc


@router.delete("/me/assets/{slot}", response_model=NationRead)
def delete_nation_asset(slot: str, current_user: Annotated[User, Depends(get_current_user)], media_service: Annotated[NationMediaService, Depends(get_nation_media_service)]) -> NationRead:
    try:
        nation = media_service.delete_nation_asset(current_user, slot)
        return NationService(media_service.session, media_service.server_id).get_by_slug(nation.slug, viewer=current_user)
    except NationMediaValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=translate_user_message(str(exc))) from exc
    except NationPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=translate_user_message(str(exc))) from exc
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=translate_user_message(str(exc))) from exc
