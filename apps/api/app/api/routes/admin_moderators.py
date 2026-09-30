from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from apps.api.app.core.audit import record_audit
from apps.api.app.core.permissions import (
    MODERATOR_PRESET,
    PERMISSION_CATALOG,
    SERVER_ADMIN_KEYS,
    sanitize_permissions,
    sanitize_server_permissions,
)
from apps.api.app.db import get_db_session
from apps.api.app.core.staff_authority import Authority, top_position
from apps.api.app.dependencies.admin import get_current_staff_user, require_reauth
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.staff_role import StaffRoleMember
from apps.api.app.models.user import User
from apps.api.app.utils.normalization import normalize_site_login

# Staff management — who may change whom is decided in core/staff_authority.py: the owner
# appoints platform admins; platform admins everything else; admins of servers their
# servers; people with roles.manage / roles.assign the roles below their own.
router = APIRouter(prefix="/admin/moderators", tags=["admin", "moderators"])


class RoleBadge(BaseModel):
    id: str
    name: str
    color: str
    position: int
    is_badge: bool = False


class ModeratorRead(BaseModel):
    id: str
    site_login: str
    email: str
    # Personal grants — platform-wide: global keys, and per-server keys granted on every server.
    permissions: list[str]
    # Personal per-server grants, by server slug.
    server_permissions: dict[str, list[str]] = {}
    # owner | admin | server_admin | moderator
    role: str
    # Servers (slugs) this person is an admin of.
    admin_servers: list[str] = []
    roles: list[RoleBadge] = []
    staff_since: str | None = None
    granted_by: str | None = None
    # What the caller may do with this person: change them at all, and whose personal
    # grants (None = all of them, incl. the platform-wide list; [] = none).
    editable: bool = False
    personal_scope: list[str] | None = []
    # 2FA set up, and how many devices are signed in.
    mfa_enabled: bool = False
    devices: int = 0


class ManagerInfo(BaseModel):
    owner: bool
    platform_admin: bool
    admin_servers: list[str]
    can_manage_roles: bool
    can_assign_roles: bool
    can_staff: bool = False
    can_manage_badges: bool = False
    can_assign_badges: bool = False
    top_position: int | None


class ModeratorListResponse(BaseModel):
    items: list[ModeratorRead]
    me: ManagerInfo
    # slug → name of every server, so tags read right even for servers hidden from the viewer.
    server_names: dict[str, str] = {}


class ModeratorAssignRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    permissions: list[str] = Field(default_factory=list)
    server_permissions: dict[str, list[str]] = Field(default_factory=dict)


class ModeratorUpdateRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)
    server_permissions: dict[str, list[str]] = Field(default_factory=dict)


class AdminAssignRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    # None → admin of the whole platform (the owner only); slugs → admin of those servers.
    servers: list[str] | None = None


class AdminServersRequest(BaseModel):
    servers: list[str] = Field(default_factory=list)


class PermissionCatalogResponse(BaseModel):
    catalog: list[dict]
    preset: list[str]


def get_authority(
    actor: Annotated[User, Depends(get_current_staff_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Authority:
    authority = Authority(actor)
    own_roles = [r.id for r in (actor.staff_roles or []) if not r.is_badge]
    if own_roles:
        from apps.api.app.models.staff_role import StaffRole

        authority.owns_badges = session.scalar(
            select(StaffRole.id).where(StaffRole.is_badge.is_(True), StaffRole.owner_role_id.in_(own_roles)).limit(1)
        ) is not None
    if not authority.opens_staff_pages:
        raise HTTPException(status_code=403, detail="Нет доступа к управлению персоналом")
    return authority


def get_staff_authority(authority: Annotated[Authority, Depends(get_authority)]) -> Authority:
    """The «Сотрудники» tab: platform admins and holders of staff.manage."""
    if not authority.can_staff:
        raise HTTPException(status_code=403, detail="Вкладка «Сотрудники» — по праву «Сотрудники: вкладка и личные права»")
    return authority


def _role(u: User) -> str:
    if u.is_owner:
        return "owner"
    if u.is_admin:
        return "admin"
    return "server_admin" if u.admin_server_ids else "moderator"


def _slugs(session: Session) -> dict[str, str]:
    return {str(i): slug for i, slug in session.query(GameServer.id, GameServer.slug).all()}


def _by_slug(session: Session, grants: dict | None) -> dict[str, list[str]]:
    slug_of = _slugs(session)
    return {slug_of[sid]: keys for sid, keys in sanitize_server_permissions(grants).items() if sid in slug_of}


def _ids(session: Session, slugs: list[str]) -> list[str]:
    id_of = {slug: sid for sid, slug in _slugs(session).items()}
    unknown = [slug for slug in slugs if slug not in id_of]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Нет такого сервера: {', '.join(unknown)}")
    return list(dict.fromkeys(id_of[slug] for slug in slugs))


def _by_id(session: Session, by_slug: dict[str, list[str]]) -> dict[str, list[str]]:
    ids = dict(zip(by_slug, _ids(session, list(by_slug)))) if by_slug else {}
    return sanitize_server_permissions({ids[slug]: keys for slug, keys in by_slug.items()})


def _read(u: User, session: Session, authority: Authority | None = None) -> ModeratorRead:
    slug_of = _slugs(session)
    editable = bool(authority and authority.outranks(u))
    scope: list[str] | None = []
    if editable and not u.is_admin and authority.can_staff:
        scope = None  # which keys exactly: Authority.may_grant, mirrored on the site
    return ModeratorRead(
        id=str(u.id), site_login=u.site_login, email=u.email,
        permissions=[] if u.is_admin else list(u.staff_permissions or []),
        server_permissions={} if u.is_admin else _by_slug(session, u.staff_server_permissions),
        role=_role(u),
        admin_servers=[] if u.is_admin else sorted(slug_of[s] for s in (u.admin_server_ids or []) if s in slug_of),
        roles=[RoleBadge(id=str(r.id), name=r.name, color=r.color, position=r.position, is_badge=r.is_badge) for r in (u.staff_roles or [])],
        staff_since=u.staff_since.isoformat() if u.staff_since else None,
        granted_by=u.staff_granted_by,
        editable=editable,
        personal_scope=scope,
        mfa_enabled=u.mfa_enabled,
        devices=_device_counts(session).get(u.id, 0),
    )


def _device_counts(session: Session) -> dict:
    from sqlalchemy import func

    from apps.api.app.core.security import utc_now
    from apps.api.app.models.auth_device import AuthDevice

    info = session.info.setdefault("device_counts", None)
    if info is None:
        rows = session.execute(select(AuthDevice.user_id, func.count()).where(
            AuthDevice.revoked_at.is_(None), AuthDevice.expires_at > utc_now()).group_by(AuthDevice.user_id)).all()
        info = session.info["device_counts"] = dict(rows)
    return info


def _find(session: Session, username: str) -> User:
    try:
        _, normalized = normalize_site_login(username)
    except ValueError:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user = session.scalar(select(User).where(User.site_login_normalized == normalized))
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


def _audit(session: Session, actor: User, action: str, user: User, **meta) -> None:
    record_audit(session, actor=actor, category="moderators", action=action,
                 target_type="user", target_id=str(user.id), target_label=user.site_login, meta=meta or None)


def _become_staff(user: User, actor: User) -> None:
    if not (user.is_moderator or user.is_admin):
        user.is_moderator = True
        user.staff_since = datetime.now(timezone.utc)
        user.staff_granted_by = actor.site_login


def refresh_staff_flag(session: Session, user: User) -> None:
    """After access was taken away: someone left with nothing at all is no longer staff."""
    if user.is_admin:
        return
    session.flush()
    session.refresh(user)
    real_roles = [r for r in (user.staff_roles or []) if not r.is_badge]
    if not (user.staff_permissions or user.staff_server_permissions or user.admin_server_ids or real_roles):
        user.is_moderator = False
        user.staff_since = None
        user.staff_granted_by = None


def _set_personal(session: Session, authority: Authority, user: User, permissions: list[str],
                  server_permissions: dict[str, list[str]]) -> None:
    """Personal grants: a platform admin sets them as sent; anyone else changes only the
    keys they hold themselves — every other key stays as it was."""
    wanted_global = set(sanitize_permissions(permissions))
    wanted_servers = {sid: set(keys) for sid, keys in _by_id(session, server_permissions).items()}
    if authority.platform:
        user.staff_permissions = sanitize_permissions(list(wanted_global))
    else:
        current = set(user.staff_permissions or [])
        user.staff_permissions = sanitize_permissions(
            [k for k in current if not authority.may_grant(k)] + [k for k in wanted_global if authority.may_grant(k)])
    current_servers = {sid: set(keys) for sid, keys in sanitize_server_permissions(user.staff_server_permissions).items()}
    merged: dict[str, list[str]] = {}
    for sid in set(current_servers) | set(wanted_servers):
        cur, want = current_servers.get(sid, set()), wanted_servers.get(sid, set())
        keep = {k for k in cur if not authority.may_grant(k, sid)} | {k for k in want if authority.may_grant(k, sid)}
        if keep:
            merged[sid] = sorted(keep)
    user.staff_server_permissions = merged
    user.staff_server_permissions = _drop_admin_dupes(user)


def _drop_admin_dupes(user: User) -> dict:
    """Personal per-server grants minus what being admin of that server already gives."""
    admin = {str(s) for s in (user.admin_server_ids or [])}
    out = {}
    for sid, keys in (user.staff_server_permissions or {}).items():
        kept = [k for k in keys if sid not in admin or k not in SERVER_ADMIN_KEYS]
        if kept:
            out[sid] = kept
    return out


def _me(authority: Authority, session: Session) -> ManagerInfo:
    slug_of = _slugs(session)
    return ManagerInfo(
        owner=authority.owner, platform_admin=authority.platform,
        admin_servers=sorted(slug_of[s] for s in authority.admin_servers if s in slug_of),
        can_manage_roles=authority.can_manage_roles, can_assign_roles=authority.can_assign_roles,
        can_staff=authority.can_staff, can_manage_badges=authority.can_manage_badges, can_assign_badges=authority.can_assign_badges,
        top_position=authority.top,
    )


@router.get("/catalog", response_model=PermissionCatalogResponse, dependencies=[Depends(get_authority)])
def get_catalog() -> PermissionCatalogResponse:
    return PermissionCatalogResponse(catalog=PERMISSION_CATALOG, preset=MODERATOR_PRESET)


@router.get("", response_model=ModeratorListResponse)
def list_staff(
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> ModeratorListResponse:
    """Everyone with admin-panel access: the owner, admins, server admins, then the rest."""
    rows = session.scalars(
        select(User).where(or_(User.is_moderator.is_(True), User.is_admin.is_(True)))
    ).all()
    order = {"owner": 0, "admin": 1, "server_admin": 2, "moderator": 3}
    rows = sorted(rows, key=lambda u: (order[_role(u)], -(top_position(u) if top_position(u) is not None else -10**9), u.site_login.lower()))
    return ModeratorListResponse(
        items=[_read(u, session, authority) for u in rows], me=_me(authority, session),
        server_names={slug: name for slug, name in session.query(GameServer.slug, GameServer.name).all()},
    )


def _may_touch_personal(authority: Authority, user: User | None) -> None:
    if user is not None and (user.is_moderator or user.admin_server_ids) and not authority.outranks(user):
        raise HTTPException(status_code=403, detail="Этого человека менять может только тот, кто выше")


@router.post("", response_model=ModeratorRead, status_code=status.HTTP_201_CREATED)
def assign_moderator(
    payload: ModeratorAssignRequest,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> ModeratorRead:
    actor = authority.actor
    user = _find(session, payload.username)
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Пользователь — админ платформы, у него и так все права")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Аккаунт пользователя заблокирован")
    _may_touch_personal(authority, user)
    before = list(user.staff_permissions or []) if user.is_moderator else None
    before_servers = _by_slug(session, user.staff_server_permissions) if user.is_moderator else None
    _become_staff(user, actor)
    _set_personal(session, authority, user, payload.permissions, payload.server_permissions)
    session.commit()
    session.refresh(user)
    _audit(session, actor, "assign", user, before=before, after=user.staff_permissions,
           before_servers=before_servers, after_servers=_by_slug(session, user.staff_server_permissions) or None)
    return _read(user, session, authority)


@router.patch("/{user_id}", response_model=ModeratorRead)
def update_moderator(
    user_id: UUID,
    payload: ModeratorUpdateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> ModeratorRead:
    user = session.get(User, user_id)
    if user is None or not user.is_moderator or user.is_admin:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    _may_touch_personal(authority, user)
    before = list(user.staff_permissions or [])
    before_servers = _by_slug(session, user.staff_server_permissions)
    _set_personal(session, authority, user, payload.permissions, payload.server_permissions)
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
    _audit(session, authority.actor, "update", user, added=added, removed=removed, servers=per_server or None)
    return _read(user, session, authority)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_moderator(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> None:
    """A platform admin removes someone from the staff altogether; anyone else with the
    «Сотрудники» right takes away what they could have given (their own keys, roles they
    may hand out)."""
    user = session.get(User, user_id)
    if user is None or not user.is_moderator or user.is_admin:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if not authority.outranks(user):
        raise HTTPException(status_code=403, detail="Снять этого человека может только тот, кто выше")
    before = {"permissions": list(user.staff_permissions or []),
              "servers": _by_slug(session, user.staff_server_permissions),
              "roles": [r.name for r in user.staff_roles]}
    if authority.platform:
        session.execute(delete(StaffRoleMember).where(StaffRoleMember.user_id == user.id))
        user.staff_permissions = []
        user.staff_server_permissions = {}
        user.admin_server_ids = []
    else:
        # Takes away what the actor could have given: their own keys, roles they may hand out.
        _set_personal(session, authority, user, [], {})
        mine = [r.id for r in user.staff_roles if authority.may_assign_role(r)]
        if mine:
            session.execute(delete(StaffRoleMember).where(StaffRoleMember.user_id == user.id, StaffRoleMember.role_id.in_(mine)))
    refresh_staff_flag(session, user)
    from apps.api.app.core import game_perms as gp

    gp.reconcile_all(session, authority.actor.site_login)
    session.commit()
    _audit(session, authority.actor, "revoke", user, before=before, scope="all" if authority.platform else "what_actor_holds")


# ── Admins: of the whole platform (the owner's call) or of single servers ───

@router.post("/admins", response_model=ModeratorRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_reauth)])
def appoint_admin(
    payload: AdminAssignRequest,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> ModeratorRead:
    """``servers`` empty/None → admin of the platform: every permission everywhere (the
    owner only). A list of slugs → admin of those servers: every per-server permission
    there and their staff and roles (the owner and platform admins)."""
    actor = authority.actor
    user = _find(session, payload.username)
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Аккаунт пользователя заблокирован")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Пользователь уже админ платформы")
    if payload.servers is None:
        if not authority.owner:
            raise HTTPException(status_code=403, detail="Админа всей платформы назначает только владелец")
        user.is_admin = True
        user.is_moderator = False
        user.admin_server_ids = []
        user.staff_since = datetime.now(timezone.utc)
        user.staff_granted_by = actor.site_login
        session.commit()
        session.refresh(user)
        _audit(session, actor, "appoint_admin", user, scope="platform")
        return _read(user, session, authority)
    if not authority.platform:
        raise HTTPException(status_code=403, detail="Админов серверов назначают владелец и админы платформы")
    if not payload.servers:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один сервер")
    ids = _ids(session, payload.servers)
    _become_staff(user, actor)
    user.admin_server_ids = sorted(set(user.admin_server_ids or []) | set(ids))
    user.staff_server_permissions = _drop_admin_dupes(user)
    session.commit()
    session.refresh(user)
    _audit(session, actor, "appoint_admin", user, scope="servers", servers=payload.servers)
    return _read(user, session, authority)


@router.put("/admins/{user_id}", response_model=ModeratorRead, dependencies=[Depends(require_reauth)])
def set_admin_servers(
    user_id: UUID,
    payload: AdminServersRequest,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> ModeratorRead:
    """The servers someone is an admin of; an empty list ends it."""
    if not authority.platform:
        raise HTTPException(status_code=403, detail="Админов серверов назначают владелец и админы платформы")
    user = session.get(User, user_id)
    if user is None or user.is_admin or not (user.is_moderator or user.admin_server_ids):
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    before = _slugs(session)
    was = [before.get(s, s) for s in (user.admin_server_ids or [])]
    user.admin_server_ids = sorted(_ids(session, payload.servers))
    user.staff_server_permissions = _drop_admin_dupes(user)
    if user.admin_server_ids:
        _become_staff(user, authority.actor)
    refresh_staff_flag(session, user)
    session.commit()
    session.refresh(user)
    _audit(session, authority.actor, "admin_servers", user, before=was, after=payload.servers)
    return _read(user, session, authority)


@router.delete("/admins/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_reauth)])
def remove_admin(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> None:
    """Takes admin away: of the platform — the owner only (the owner cannot be removed);
    of servers — the owner and platform admins."""
    user = session.get(User, user_id)
    if user is None or not (user.is_admin or user.admin_server_ids):
        raise HTTPException(status_code=404, detail="Админ не найден")
    if user.is_owner:
        raise HTTPException(status_code=400, detail="Владельца снять нельзя")
    if user.is_admin:
        if not authority.owner:
            raise HTTPException(status_code=403, detail="Админа всей платформы снимает только владелец")
        user.is_admin = False
        user.staff_since = None
        user.staff_granted_by = None
        session.commit()
        _audit(session, authority.actor, "remove_admin", user, scope="platform")
        return
    if not authority.platform:
        raise HTTPException(status_code=403, detail="Админов серверов снимают владелец и админы платформы")
    was = user.admin_server_ids
    user.admin_server_ids = []
    refresh_staff_flag(session, user)
    session.commit()
    _audit(session, authority.actor, "remove_admin", user, scope="servers", before=was)


# ── Sign-ins and 2FA of a staff member ───────────────────────────────────────

def _target(session: Session, authority: Authority, user_id: UUID) -> User:
    user = session.get(User, user_id)
    if user is None or not (user.is_moderator or user.is_admin or user.admin_server_ids):
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if user.id != authority.actor.id and not authority.outranks(user):
        raise HTTPException(status_code=403, detail="Этого человека менять может только тот, кто выше")
    return user


@router.get("/{user_id}/devices")
def staff_devices(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> dict:
    from apps.api.app.api.routes.security import active_devices, device_view

    user = _target(session, authority, user_id)
    return {"items": [device_view(d, None) for d in active_devices(session, user.id)], "mfa_enabled": user.mfa_enabled}


@router.post("/{user_id}/end-sessions")
def staff_end_sessions(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> dict:
    """Signs the person out everywhere — the site, the launcher, the admin panel."""
    from apps.api.app.core.sign_ins import revoke_devices

    user = _target(session, authority, user_id)
    if user.id == authority.actor.id:
        raise HTTPException(status_code=400, detail="Свои входы завершай в профиле — «Активные входы»")
    n = revoke_devices(session, user.id)
    session.commit()
    _audit(session, authority.actor, "end_sessions", user, count=n)
    return {"ended": n}


@router.post("/{user_id}/mfa-reset", dependencies=[Depends(require_reauth)])
def staff_mfa_reset(
    user_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    authority: Annotated[Authority, Depends(get_staff_authority)],
) -> dict:
    """Lost phone: turns the person's 2FA off and signs them out; on the next visit to the
    admin panel they set it up again. The owner and platform admins only."""
    from apps.api.app.core.sign_ins import revoke_devices

    if not authority.platform:
        raise HTTPException(status_code=403, detail="Сбросить 2FA может владелец или админ платформы")
    user = _target(session, authority, user_id)
    if user.is_owner and not authority.owner:
        raise HTTPException(status_code=403, detail="2FA владельца сбрасывает только он сам")
    user.mfa_totp_secret = None
    user.mfa_totp_enabled_at = None
    user.mfa_totp_last_step = None
    user.mfa_telegram_enabled_at = None
    user.mfa_backup_hashes = []
    user.mfa_passkeys.clear()
    n = revoke_devices(session, user.id)
    session.commit()
    _audit(session, authority.actor, "mfa_reset", user, devices_signed_out=n)
    return {"ok": True}
