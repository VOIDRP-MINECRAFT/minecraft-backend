from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.permissions import (
    MODERATOR_PRESET,
    PERMISSION_CATALOG,
    sanitize_permissions,
)
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.models.user import User
from apps.api.app.utils.normalization import normalize_site_login

# Admin-only (require_admin_access rejects moderators): moderators can never
# manage other moderators or see this section.
router = APIRouter(
    prefix="/admin/moderators",
    tags=["admin", "moderators"],
    dependencies=[Depends(require_admin_access)],
)


class ModeratorRead(BaseModel):
    id: str
    site_login: str
    email: str
    permissions: list[str]


class ModeratorListResponse(BaseModel):
    items: list[ModeratorRead]


class ModeratorAssignRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    permissions: list[str] = Field(default_factory=list)


class ModeratorUpdateRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class PermissionCatalogResponse(BaseModel):
    catalog: list[dict]
    preset: list[str]


def _read(u: User) -> ModeratorRead:
    return ModeratorRead(
        id=str(u.id), site_login=u.site_login, email=u.email,
        permissions=list(u.staff_permissions or []),
    )


@router.get("/catalog", response_model=PermissionCatalogResponse)
def get_catalog() -> PermissionCatalogResponse:
    return PermissionCatalogResponse(catalog=PERMISSION_CATALOG, preset=MODERATOR_PRESET)


@router.get("", response_model=ModeratorListResponse)
def list_moderators(session: Annotated[Session, Depends(get_db_session)]) -> ModeratorListResponse:
    rows = session.scalars(
        select(User).where(User.is_moderator.is_(True)).order_by(User.site_login)
    ).all()
    return ModeratorListResponse(items=[_read(u) for u in rows])


@router.post("", response_model=ModeratorRead, status_code=status.HTTP_201_CREATED)
def assign_moderator(
    payload: ModeratorAssignRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> ModeratorRead:
    _, normalized = normalize_site_login(payload.username)
    user = session.scalar(select(User).where(User.site_login_normalized == normalized))
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Пользователь — админ, роль модератора не нужна")
    user.is_moderator = True
    user.staff_permissions = sanitize_permissions(payload.permissions)
    session.commit()
    session.refresh(user)
    return _read(user)


@router.patch("/{user_id}", response_model=ModeratorRead)
def update_moderator(
    user_id: UUID,
    payload: ModeratorUpdateRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> ModeratorRead:
    user = session.get(User, user_id)
    if user is None or not user.is_moderator:
        raise HTTPException(status_code=404, detail="Модератор не найден")
    user.staff_permissions = sanitize_permissions(payload.permissions)
    session.commit()
    session.refresh(user)
    return _read(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_moderator(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    user = session.get(User, user_id)
    if user is None or not user.is_moderator:
        raise HTTPException(status_code=404, detail="Модератор не найден")
    user.is_moderator = False
    user.staff_permissions = []
    session.commit()
