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
        members=(members if members is not None else _members(session)).get(role.id, []),
        editable=authority.may_edit_role(role.position, role.server_ids, role.permissions),
        assignable=authority.may_assign_role(role),
    )


def _validated(session: Session, body: RoleBody) -> tuple[str, str, list[str] | None, list[str]]:
    if not _COLOR.match(body.color):
        raise HTTPException(status_code=400, detail="Цвет — в виде #RRGGBB")
    server_ids = None if body.servers is None else _ids(session, body.servers)
    if server_ids is not None and not server_ids:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один сервер или «все серверы»")
    keys = sanitize_permissions(body.permissions)
    if server_ids is not None:
        platform = [k for k in keys if k not in SERVER_KEYS]
        if platform:
            raise HTTPException(status_code=400, detail="Роль отдельных серверов не может давать права платформы: " + ", ".join(platform))
    return body.name.strip(), body.color.lower(), server_ids, keys


def _get(session: Session, role_id: UUID) -> StaffRole:
    role = session.get(StaffRole, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    return role


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
    return RoleListResponse(items=[_read(r, session, authority, members) for r in roles], me=_me(authority, session))


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    body: RoleBody,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleRead:
    """A new role goes to the bottom of the list, as in Discord."""
    name, color, server_ids, keys = _validated(session, body)
    lowest = session.scalar(select(StaffRole.position).order_by(StaffRole.position.asc()).limit(1))
    position = (lowest - 10) if lowest is not None else 0
    if not authority.may_edit_role(position, server_ids, keys):
        raise HTTPException(status_code=403, detail="Такую роль создать нельзя: в ней права, которых у тебя нет, или серверы не твои")
    role = StaffRole(name=name, color=color, position=position, server_ids=server_ids, permissions=keys,
                     created_by=authority.actor.site_login)
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
    if not authority.may_edit_role(role.position, role.server_ids, role.permissions):
        raise _deny_edit()
    name, color, server_ids, keys = _validated(session, body)
    if not authority.may_edit_role(role.position, server_ids, keys):
        raise HTTPException(status_code=403, detail="Так изменить нельзя: в роли права, которых у тебя нет, или серверы не твои")
    before = {"name": role.name, "permissions": list(role.permissions or []), "servers": role.server_ids}
    role.name, role.color, role.server_ids, role.permissions = name, color, server_ids, keys
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
    if not authority.may_edit_role(role.position, role.server_ids, role.permissions):
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
    """The whole list, most senior first. Roles the caller may not change keep their
    places; the ones they may change move only among the places below the caller's own
    highest role."""
    roles = {r.id: r for r in session.scalars(select(StaffRole)).all()}
    if set(body.ids) != set(roles) or len(body.ids) != len(roles):
        raise HTTPException(status_code=400, detail="Список ролей устарел — обновите страницу")
    current = sorted(roles.values(), key=lambda r: (-r.position, r.name))
    if not authority.platform:
        top_index = next((i for i, r in enumerate(current) if authority.top is not None and r.position == authority.top), None)
        for i, (old, new_id) in enumerate(zip(current, body.ids)):
            new = roles[new_id]
            if old.id == new.id:
                continue
            movable = (authority.may_edit_role(new.position, new.server_ids, new.permissions)
                       and authority.may_edit_role(old.position, old.server_ids, old.permissions))
            if not movable or (top_index is not None and i <= top_index) or (top_index is None and not authority.admin_servers):
                raise HTTPException(status_code=403, detail="Двигать можно только свои роли и только ниже своей")
    n = len(body.ids)
    for i, rid in enumerate(body.ids):
        roles[rid].position = (n - i) * 10
    session.commit()
    record_audit(session, actor=authority.actor, category="roles", action="reorder",
                 meta={"order": [roles[rid].name for rid in body.ids]})
    members = _members(session)
    fresh = sorted(roles.values(), key=lambda r: -r.position)
    return RoleListResponse(items=[_read(r, session, authority, members) for r in fresh], me=_me(authority, session))


@router.post("/{role_id}/members", response_model=RoleRead)
def add_member(
    role_id: UUID,
    body: MemberBody,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_authority)],
) -> RoleRead:
    role = _get(session, role_id)
    if not authority.may_assign_role(role):
        raise HTTPException(status_code=403, detail="Эту роль выдать нельзя: она не ниже твоей или даёт права, которых у тебя нет")
    user = _find(session, body.username)
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Аккаунт пользователя заблокирован")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Это админ платформы — у него и так все права")
    if (user.is_moderator or user.admin_server_ids) and user.id != authority.actor.id and not authority.outranks(user):
        raise HTTPException(status_code=403, detail="Этого человека менять может только тот, кто выше")
    if user.id == authority.actor.id and not authority.platform:
        raise HTTPException(status_code=403, detail="Себе роли выдавать нельзя")
    exists = session.get(StaffRoleMember, (role.id, user.id))
    if exists is None:
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
    if not authority.may_assign_role(role) or not authority.outranks(user):
        raise HTTPException(status_code=403, detail="Снять эту роль может только тот, кто выше")
    session.execute(delete(StaffRoleMember).where(StaffRoleMember.role_id == role.id, StaffRoleMember.user_id == user.id))
    refresh_staff_flag(session, user)
    session.commit()
    _audit(session, authority.actor, "role_remove", user, role=role.name)
    return _read(role, session, authority)
