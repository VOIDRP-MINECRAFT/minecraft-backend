"""Roles, like Discord's: named, coloured bundles of permissions in an order.

Who may create, edit, delete, reorder and hand out which role is decided in
core/staff_authority.py (Authority.may_edit_role / may_assign_role).
"""
from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.api.routes.admin_moderators import (
    _audit, _become_staff, _find, _ids, _me, _slugs, get_authority, refresh_staff_flag, ManagerInfo,
)
from apps.api.app.core.audit import record_audit
from apps.api.app.core.permissions import SERVER_KEYS, sanitize_permissions
from apps.api.app.core.staff_authority import Authority
from apps.api.app.db import get_db_session
from apps.api.app.models.staff_role import StaffRole, StaffRoleMember
from apps.api.app.models.user import User

router = APIRouter(prefix="/admin/roles", tags=["admin", "roles"])

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class RoleMember(BaseModel):
    id: str
    site_login: str


class RoleRead(BaseModel):
    id: str
    name: str
    color: str
    position: int
    # None = every server (and platform keys); slugs = only those servers.
    servers: list[str] | None
    permissions: list[str]
    # A badge: a label about the person, never any permission, no seniority.
    is_badge: bool = False
    # For a badge: the role that owns it (its members hand it out).
    owner_role: dict | None = None
    # The viewer holds this role / badge.
    mine: bool = False
    members: list[RoleMember]
    editable: bool
    assignable: bool


class RoleListResponse(BaseModel):
    items: list[RoleRead]
    me: ManagerInfo


class RoleBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=48)
    color: str = "#99aab5"
    servers: list[str] | None = None
    permissions: list[str] = Field(default_factory=list)
    badge: bool = False
    # Badges only: tie it to a role (id) whose members then own it; None = not tied.
    owner_role_id: UUID | None = None


class RoleOrder(BaseModel):
    # Every role id, most senior first.
    ids: list[UUID]


class MemberBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)


def _members(session: Session) -> dict[UUID, list[RoleMember]]:
    rows = session.execute(
        select(StaffRoleMember.role_id, User.id, User.site_login)
        .join(User, User.id == StaffRoleMember.user_id)
        .order_by(User.site_login)
    ).all()
    out: dict[UUID, list[RoleMember]] = {}
    for role_id, uid, login in rows:
        out.setdefault(role_id, []).append(RoleMember(id=str(uid), site_login=login))
    return out


def _read(role: StaffRole, session: Session, authority: Authority, members=None) -> RoleRead:
    slug_of = _slugs(session)
    return RoleRead(
        id=str(role.id), name=role.name, color=role.color, position=role.position,
        servers=None if role.server_ids is None else [slug_of[s] for s in role.server_ids if s in slug_of],
        permissions=list(role.permissions or []),
        is_badge=role.is_badge,
        owner_role={"id": str(role.owner_role.id), "name": role.owner_role.name, "color": role.owner_role.color}
        if role.is_badge and role.owner_role is not None else None,
        mine=authority.is_member(role),
        members=(members if members is not None else _members(session)).get(role.id, []),
        editable=_may_edit(authority, role.is_badge, role.position, role.server_ids, role.permissions, role.owner_role),
        assignable=authority.may_assign_role(role),
    )


def _may_edit(authority: Authority, badge: bool, position: int, server_ids, permissions, owner_role=None) -> bool:
    if badge:
        return authority.may_edit_badge(server_ids, owner_role)
    return authority.may_edit_role(position, server_ids, permissions)


def _validated(session: Session, body: RoleBody) -> tuple[str, str, list[str] | None, list[str]]:
    if not _COLOR.match(body.color):
        raise HTTPException(status_code=400, detail="Цвет — в виде #RRGGBB")
    server_ids = None if body.servers is None else _ids(session, body.servers)
    if server_ids is not None and not server_ids:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один сервер или «все серверы»")
    keys = [] if body.badge else sanitize_permissions(body.permissions)
    if server_ids is not None:
        platform = [k for k in keys if k not in SERVER_KEYS]
        if platform:
            raise HTTPException(status_code=400, detail="Роль отдельных серверов не может давать права платформы: " + ", ".join(platform))
    return body.name.strip(), body.color.lower(), server_ids, keys


def _owner_role(session: Session, authority: Authority, body: RoleBody) -> StaffRole | None:
    if not body.badge or body.owner_role_id is None:
        return None
    owner = session.get(StaffRole, body.owner_role_id)
    if owner is None or owner.is_badge:
        raise HTTPException(status_code=400, detail="Значок можно привязать только к существующей роли")
    if not authority.may_own_badge(owner):
        raise HTTPException(status_code=403, detail="Привязать значок можно к своей роли или к роли, которой управляешь")
    return owner


def _get(session: Session, role_id: UUID) -> StaffRole:
    role = session.get(StaffRole, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    return role


_BADGE_DENY = "Нужно право «Значки: создавать и править» — на этом сервере, а для общего значка на всех"


def _deny_edit() -> HTTPException:
    return HTTPException(status_code=403, detail="Эту роль менять нельзя: она не ниже твоей или даёт права, которых у тебя нет")


def _log(session: Session, authority: Authority, action: str, role: StaffRole, **meta) -> None:
    record_audit(session, actor=authority.actor, category="roles", action=action, target_type="role",
                 target_id=str(role.id), target_label=role.name, meta=meta or None)


@router.get("", response_model=RoleListResponse)
def list_roles(
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleListResponse:
    roles = session.scalars(select(StaffRole).order_by(StaffRole.position.desc(), StaffRole.name)).all()
    members = _members(session)
    # Only what the viewer may change or hand out, and their own roles and badges.
    return RoleListResponse(items=[_read(r, session, authority, members) for r in roles if authority.sees_role(r)],
                            me=_me(authority, session))


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    body: RoleBody,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleRead:
    """A new role goes to the bottom of the list, as in Discord."""
    name, color, server_ids, keys = _validated(session, body)
    owner = _owner_role(session, authority, body)
    lowest = session.scalar(select(StaffRole.position).order_by(StaffRole.position.asc()).limit(1))
    position = (lowest - 10) if lowest is not None else 0
    # A badge tied to a role lives on that role's servers; making one still needs badges.manage.
    if body.badge and owner is not None:
        server_ids = owner.server_ids
    if body.badge and not authority.can_manage_badges:
        raise HTTPException(status_code=403, detail=_BADGE_DENY)
    if not _may_edit(authority, body.badge, position, server_ids, keys, owner):
        raise HTTPException(status_code=403, detail=_BADGE_DENY if body.badge else "Такую роль создать нельзя: в ней права, которых у тебя нет, или серверы не твои")
    role = StaffRole(name=name, color=color, position=position, server_ids=server_ids, permissions=keys,
                     created_by=authority.actor.site_login, is_badge=body.badge, owner_role_id=owner.id if owner else None)
    session.add(role)
    session.commit()
    session.refresh(role)
    _log(session, authority, "create", role, servers=body.servers, permissions=keys)
    return _read(role, session, authority)


@router.patch("/{role_id}", response_model=RoleRead)
def update_role(
    role_id: UUID,
    body: RoleBody,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleRead:
    role = _get(session, role_id)
    if not _may_edit(authority, role.is_badge, role.position, role.server_ids, role.permissions, role.owner_role):
        raise HTTPException(status_code=403, detail=_BADGE_DENY) if role.is_badge else _deny_edit()
    body.badge = role.is_badge  # a badge stays a badge, a role stays a role
    name, color, server_ids, keys = _validated(session, body)
    owner = _owner_role(session, authority, body) if body.owner_role_id != role.owner_role_id else role.owner_role
    if role.is_badge and owner is not None:
        server_ids = owner.server_ids
    if not _may_edit(authority, role.is_badge, role.position, server_ids, keys, owner):
        raise HTTPException(status_code=403, detail="Так изменить нельзя: в роли права, которых у тебя нет, или серверы не твои")
    before = {"name": role.name, "permissions": list(role.permissions or []), "servers": role.server_ids}
    role.name, role.color, role.server_ids, role.permissions = name, color, server_ids, keys
    if role.is_badge:
        role.owner_role_id = owner.id if owner else None
    session.commit()
    session.refresh(role)
    added = [k for k in keys if k not in before["permissions"]]
    removed = [k for k in before["permissions"] if k not in keys]
    _log(session, authority, "update", role, added=added or None, removed=removed or None,
         servers_before=before["servers"], servers_after=server_ids, renamed_from=before["name"] if before["name"] != name else None)
    return _read(role, session, authority)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> None:
    role = _get(session, role_id)
    if not _may_edit(authority, role.is_badge, role.position, role.server_ids, role.permissions, role.owner_role):
        raise _deny_edit()
    member_ids = [uid for (uid,) in session.execute(select(StaffRoleMember.user_id).where(StaffRoleMember.role_id == role.id)).all()]
    _log(session, authority, "delete", role, permissions=list(role.permissions or []), members=len(member_ids))
    session.delete(role)
    session.flush()
    for uid in member_ids:
        user = session.get(User, uid)
        if user is not None:
            refresh_staff_flag(session, user)
    session.commit()


@router.put("/order", response_model=RoleListResponse)
def reorder_roles(
    body: RoleOrder,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleListResponse:
    """The roles the caller sees, most senior first. They swap among their own places;
    roles the caller does not see keep theirs. Only roles the caller may change move, and
    only to places below the caller's own highest role."""
    roles = {r.id: r for r in session.scalars(select(StaffRole).where(StaffRole.is_badge.is_(False))).all()}
    ids = list(dict.fromkeys(body.ids))
    if not ids or any(i not in roles for i in ids):
        raise HTTPException(status_code=400, detail="Список ролей устарел — обновите страницу")
    current = sorted((roles[i] for i in ids), key=lambda r: (-r.position, r.name))
    slots = [r.position for r in current]
    if len(set(slots)) < len(slots):  # equal positions: spread them first, order kept
        ordered = sorted(roles.values(), key=lambda r: (-r.position, r.name))
        for n, r in enumerate(ordered):
            r.position = (len(ordered) - n) * 10
        current = sorted((roles[i] for i in ids), key=lambda r: -r.position)
        slots = [r.position for r in current]
    for old, new_id, slot in zip(current, ids, slots):
        new = roles[new_id]
        if old.id == new.id or authority.platform:
            continue
        movable = (authority.may_edit_role(new.position, new.server_ids, new.permissions)
                   and authority.may_edit_role(old.position, old.server_ids, old.permissions))
        below = authority.top is None or slot < authority.top
        if not movable or not below:
            raise HTTPException(status_code=403, detail="Двигать можно только свои роли и только ниже своей")
    for new_id, slot in zip(ids, slots):
        roles[new_id].position = slot
    session.commit()
    record_audit(session, actor=authority.actor, category="roles", action="reorder",
                 meta={"order": [roles[i].name for i in ids]})
    return list_roles(session, authority)


@router.post("/{role_id}/members", response_model=RoleRead)
def add_member(
    role_id: UUID,
    body: MemberBody,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleRead:
    role = _get(session, role_id)
    if not authority.may_assign_role(role):
        raise HTTPException(status_code=403, detail="Нужно право «Значки: выдавать» на серверах этого значка" if role.is_badge
                            else "Эту роль выдать нельзя: она не ниже твоей или даёт права, которых у тебя нет")
    user = _find(session, body.username)
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Аккаунт пользователя заблокирован")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Это админ платформы — у него и так все права")
    myself = user.id == authority.actor.id
    if (user.is_moderator or user.admin_server_ids) and not myself and not authority.outranks(user):
        raise HTTPException(status_code=403, detail="Этого человека менять может только тот, кто выше")
    if role.is_badge:
        # A badge is a label on a staff member; it neither grants access nor makes staff.
        if not (user.is_moderator or user.is_admin or user.admin_server_ids):
            raise HTTPException(status_code=400, detail="Значки выдаются только сотрудникам")
    elif myself and not authority.platform:
        raise HTTPException(status_code=403, detail="Себе роли выдавать нельзя — только значки")
    exists = session.get(StaffRoleMember, (role.id, user.id))
    if exists is None:
        if not role.is_badge:
            _become_staff(user, authority.actor)
        session.add(StaffRoleMember(role_id=role.id, user_id=user.id, granted_by=authority.actor.site_login))
        session.commit()
        _audit(session, authority.actor, "role_add", user, role=role.name)
    return _read(role, session, authority)


@router.delete("/{role_id}/members/{user_id}", response_model=RoleRead)
def remove_member(
    role_id: UUID,
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleRead:
    role = _get(session, role_id)
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    myself = user.id == authority.actor.id and role.is_badge
    if not authority.may_assign_role(role) or not (myself or authority.outranks(user)):
        raise HTTPException(status_code=403, detail="Снять эту роль может только тот, кто выше")
    session.execute(delete(StaffRoleMember).where(StaffRoleMember.role_id == role.id, StaffRoleMember.user_id == user.id))
    refresh_staff_flag(session, user)
    session.commit()
    _audit(session, authority.actor, "role_remove", user, role=role.name)
    return _read(role, session, authority)
