from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.app.core.audit import record_audit
from apps.api.app.core.permissions import (
    MODERATOR_PRESET,
    PERMISSION_CATALOG,
    sanitize_permissions,
    sanitize_server_permissions,
)
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_staff_user, require_admin_access
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.utils.normalization import normalize_site_login

# Admin-only (require_admin_access rejects moderators): moderators can never manage
# other staff or see this section. Among admins, only the owner appoints and removes
# admins; every admin manages moderators.
router = APIRouter(
    prefix="/admin/moderators",
    tags=["admin", "moderators"],
    dependencies=[Depends(require_admin_access)],
)


class ModeratorRead(BaseModel):
    id: str
    site_login: str
    email: str
    # Platform-wide: global keys, and per-server keys granted on every server.
    permissions: list[str]
    # Per-server grants, by server slug.
    server_permissions: dict[str, list[str]] = {}
    # owner | admin | moderator
    role: str
    staff_since: str | None = None
    granted_by: str | None = None


class ModeratorListResponse(BaseModel):
    items: list[ModeratorRead]


class ModeratorAssignRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    permissions: list[str] = Field(default_factory=list)
    server_permissions: dict[str, list[str]] = Field(default_factory=dict)


class ModeratorUpdateRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)
    server_permissions: dict[str, list[str]] = Field(default_factory=dict)


class AdminAssignRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)


class PermissionCatalogResponse(BaseModel):
    catalog: list[dict]
    preset: list[str]


def _role(u: User) -> str:
    if u.is_owner:
        return "owner"
    return "admin" if u.is_admin else "moderator"


def _slugs(session: Session) -> dict[str, str]:
    return {str(i): slug for i, slug in session.query(GameServer.id, GameServer.slug).all()}


def _by_slug(session: Session, grants: dict | None) -> dict[str, list[str]]:
    slug_of = _slugs(session)
    return {slug_of[sid]: keys for sid, keys in sanitize_server_permissions(grants).items() if sid in slug_of}


def _by_id(session: Session, by_slug: dict[str, list[str]]) -> dict[str, list[str]]:
    id_of = {slug: sid for sid, slug in _slugs(session).items()}
    unknown = [slug for slug in by_slug if slug not in id_of]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Нет такого сервера: {', '.join(unknown)}")
    return sanitize_server_permissions({id_of[slug]: keys for slug, keys in by_slug.items()})


def _read(u: User, session: Session | None = None) -> ModeratorRead:
    return ModeratorRead(
        id=str(u.id), site_login=u.site_login, email=u.email,
        permissions=[] if u.is_admin else list(u.staff_permissions or []),
        server_permissions={} if (u.is_admin or session is None) else _by_slug(session, u.staff_server_permissions),
        role=_role(u),
        staff_since=u.staff_since.isoformat() if u.staff_since else None,
        granted_by=u.staff_granted_by,
    )


def _find(session: Session, username: str) -> User:
    _, normalized = normalize_site_login(username)
    user = session.scalar(select(User).where(User.site_login_normalized == normalized))
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


def _audit(session: Session, actor: User, action: str, user: User, **meta) -> None:
    record_audit(session, actor=actor, category="moderators", action=action,
                 target_type="user", target_id=str(user.id), target_label=user.site_login, meta=meta or None)


@router.get("/catalog", response_model=PermissionCatalogResponse)
def get_catalog() -> PermissionCatalogResponse:
    return PermissionCatalogResponse(catalog=PERMISSION_CATALOG, preset=MODERATOR_PRESET)


@router.get("", response_model=ModeratorListResponse)
def list_staff(session: Annotated[Session, Depends(get_db_session)]) -> ModeratorListResponse:
    """Everyone with admin-panel access: the owner, admins, then moderators."""
    rows = session.scalars(
        select(User).where(or_(User.is_moderator.is_(True), User.is_admin.is_(True)))
    ).all()
    order = {"owner": 0, "admin": 1, "moderator": 2}
    rows = sorted(rows, key=lambda u: (order[_role(u)], u.site_login.lower()))
    return ModeratorListResponse(items=[_read(u, session) for u in rows])


@router.post("", response_model=ModeratorRead, status_code=status.HTTP_201_CREATED)
def assign_moderator(
    payload: ModeratorAssignRequest,
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> ModeratorRead:
    user = _find(session, payload.username)
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Пользователь — админ, роль модератора не нужна")
    before = list(user.staff_permissions or []) if user.is_moderator else None
    before_servers = _by_slug(session, user.staff_server_permissions) if user.is_moderator else None
    user.is_moderator = True
    user.staff_permissions = sanitize_permissions(payload.permissions)
    user.staff_server_permissions = _by_id(session, payload.server_permissions)
    if before is None:
        user.staff_since = datetime.now(timezone.utc)
        user.staff_granted_by = actor.site_login
    session.commit()
    session.refresh(user)
    _audit(session, actor, "assign", user, before=before, after=user.staff_permissions,
           before_servers=before_servers, after_servers=payload.server_permissions or None)
    return _read(user, session)


@router.patch("/{user_id}", response_model=ModeratorRead)
def update_moderator(
    user_id: UUID,
    payload: ModeratorUpdateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> ModeratorRead:
    user = session.get(User, user_id)
    if user is None or not user.is_moderator or user.is_admin:
        raise HTTPException(status_code=404, detail="Модератор не найден")
    before = list(user.staff_permissions or [])
    before_servers = _by_slug(session, user.staff_server_permissions)
    user.staff_permissions = sanitize_permissions(payload.permissions)
    user.staff_server_permissions = _by_id(session, payload.server_permissions)
    session.commit()
    session.refresh(user)
    after_servers = _by_slug(session, user.staff_server_permissions)
    added = [k for k in user.staff_permissions if k not in before]
    removed = [k for k in before if k not in user.staff_permissions]
    per_server = {}
    for slug in set(before_servers) | set(after_servers):
        b, a = before_servers.get(slug, []), after_servers.get(slug, [])
        diff = {"added": [k for k in a if k not in b], "removed": [k for k in b if k not in a]}
        if diff["added"] or diff["removed"]:
            per_server[slug] = diff
    _audit(session, actor, "update", user, added=added, removed=removed, servers=per_server or None)
    return _read(user, session)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_moderator(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> None:
    user = session.get(User, user_id)
    if user is None or not user.is_moderator or user.is_admin:
        raise HTTPException(status_code=404, detail="Модератор не найден")
    before = list(user.staff_permissions or [])
    user.is_moderator = False
    user.staff_permissions = []
    user.staff_server_permissions = {}
    user.staff_since = None
    user.staff_granted_by = None
    session.commit()
    _audit(session, actor, "revoke", user, before=before)


# ── Full admins — the owner's alone ─────────────────────────────────────────

def _require_owner(actor: User) -> None:
    if not actor.is_owner:
        raise HTTPException(status_code=403, detail="Назначать и снимать админов может только владелец")


@router.post("/admins", response_model=ModeratorRead, status_code=status.HTTP_201_CREATED)
def appoint_admin(
    payload: AdminAssignRequest,
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> ModeratorRead:
    """Makes someone a full admin: every permission on every server, and managing moderators."""
    _require_owner(actor)
    user = _find(session, payload.username)
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Пользователь уже админ")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Аккаунт пользователя заблокирован")
    was = list(user.staff_permissions or []) if user.is_moderator else None
    user.is_admin = True
    user.is_moderator = False
    user.staff_permissions = []
    user.staff_server_permissions = {}
    user.staff_since = datetime.now(timezone.utc)
    user.staff_granted_by = actor.site_login
    session.commit()
    session.refresh(user)
    _audit(session, actor, "appoint_admin", user, was_moderator_with=was)
    return _read(user, session)


@router.delete("/admins/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_admin(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[User, Depends(get_current_staff_user)],
) -> None:
    """Takes full admin away. The owner cannot be removed — there is always one."""
    _require_owner(actor)
    user = session.get(User, user_id)
    if user is None or not user.is_admin:
        raise HTTPException(status_code=404, detail="Админ не найден")
    if user.is_owner:
        raise HTTPException(status_code=400, detail="Владельца снять нельзя")
    user.is_admin = False
    user.staff_since = None
    user.staff_granted_by = None
    session.commit()
    _audit(session, actor, "remove_admin", user)
