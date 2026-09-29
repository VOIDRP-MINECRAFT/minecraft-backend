from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from apps.api.app.core.permissions import resolve_user_permissions
from apps.api.app.core.security import decode_access_token
from apps.api.app.db import get_db_session
from apps.api.app.models.user import User

_optional_bearer = HTTPBearer(auto_error=False)


def require_admin_access(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    """A signed-in full admin (``users.is_admin``). Nothing else gets in: there used to be
    a shared X-Admin-Api-Secret header that granted everything and left no name in the
    audit log; it was removed on 2026-09-29 — every admin action is a person's."""
    user = _user_from_credentials(credentials, session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required")
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


# ── Staff (moderator) RBAC ──────────────────────────────────────────────────

def _user_from_credentials(
    credentials: HTTPAuthorizationCredentials | None, session: Session
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        from uuid import UUID
        user = session.get(User, UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    if user is None or not user.is_active:
        return None
    if user.is_admin or user.is_moderator or user.admin_server_ids:
        _require_staff_mfa(user, credentials.credentials, session)
    return user


def _require_staff_mfa(user: User, token: str, session: Session) -> None:
    """The admin panel needs 2FA: set up on the account, and passed on this device within
    the last 12 hours. The site answers ``mfa_setup_required`` / ``mfa_required`` with its
    own screens; a signed-out device gets 401 ``session_revoked``."""
    from apps.api.app.config import get_settings
    from apps.api.app.core.mfa import MFA_TTL
    from apps.api.app.core.security import utc_now
    from apps.api.app.dependencies.auth import device_from_token

    if not getattr(get_settings(), "staff_mfa_required", True):
        return
    device = device_from_token(token, session)
    if device is None or device.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_revoked")
    if not user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="mfa_setup_required")
    if device.mfa_at is None or utc_now() - device.mfa_at >= MFA_TTL:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="mfa_required")


def reauth_is_fresh(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> bool:
    from apps.api.app.core.mfa import REAUTH_TTL
    from apps.api.app.core.security import utc_now
    from apps.api.app.dependencies.auth import device_from_token

    device = device_from_token(credentials.credentials, session) if credentials else None
    return bool(device and device.reauth_at and utc_now() - device.reauth_at < REAUTH_TTL)


def require_reauth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    """Dangerous actions: the password re-entered on this device within 5 minutes
    (POST /auth/reauth). The site answers ``reauth_required`` with a password dialog."""
    from apps.api.app.core.mfa import REAUTH_TTL
    from apps.api.app.core.security import utc_now
    from apps.api.app.dependencies.auth import device_from_token

    device = device_from_token(credentials.credentials, session) if credentials else None
    if device is None or device.reauth_at is None or utc_now() - device.reauth_at >= REAUTH_TTL:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reauth_required")


def request_server_id(request: Request, session: Session):
    """The server a request is about, the way the admin panel says it: ``?server=<slug>``,
    ``?server_id=<uuid>`` (news) or the ``X-Server-Slug`` header, else the default server.
    None for a server that does not exist — then no per-server permission applies."""
    from uuid import UUID as _UUID

    from apps.api.app.models.game_server import GameServer

    slug = request.query_params.get("server") or request.headers.get("x-server-slug")
    raw_id = request.query_params.get("server_id")
    if raw_id:
        try:
            server = session.get(GameServer, _UUID(raw_id))
        except ValueError:
            return None
        return server.id if server else None
    if slug:
        found = session.query(GameServer.id).filter(GameServer.slug == slug).first()
        return found[0] if found else None
    default = session.query(GameServer.id).filter(GameServer.is_default.is_(True)).first()
    return default[0] if default else None


def caller_permissions(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> set[str]:
    """Effective permission set of the caller, on the server the request is about.

    Full admins get every key; moderators get their platform-wide grants plus what
    they were given on this server (see resolve_user_permissions). Every
    ``require_permission`` goes through here, so each admin route is checked for
    the server it acts on. Raises 401/403 if the caller is not staff at all.
    """
    user = _user_from_credentials(credentials, session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required")
    if not (user.is_admin or user.is_moderator):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
    if user.is_admin:
        return resolve_user_permissions(user)
    return resolve_user_permissions(user, request_server_id(request, session))


def require_permission(key: str):
    """Dependency factory: 403 unless the caller holds ``key`` (admins bypass)."""

    def _dep(perms: Annotated[set[str], Depends(caller_permissions)]) -> None:
        if key not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {key}"
            )

    return _dep


def require_any_permission(*keys: str):
    """Dependency factory: allow if the caller holds ANY of ``keys`` (admins bypass)."""

    def _dep(perms: Annotated[set[str], Depends(caller_permissions)]) -> None:
        if not any(k in perms for k in keys):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission"
            )

    return _dep


def get_current_staff_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    """Current JWT user if they are a full admin or a moderator (else 403).

    Use where the endpoint needs the acting user object (e.g. news author).
    """
    user = _user_from_credentials(credentials, session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth required")
    if not (user.is_admin or user.is_moderator):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
    return user

class PermittedServers:
    """Where the caller holds a permission: everywhere (``all``: a full admin, or the key
    granted on every server — which also covers records tied to no server), or on the
    servers in ``ids``. For pages that list records of all servers at once (audit log,
    feedback, mod suggestions, launcher crashes): the list keeps to these servers."""

    def __init__(self, all_: bool, ids: set):
        self.all = all_
        self.ids = ids

    def allows(self, server_id) -> bool:
        return self.all or (server_id is not None and server_id in self.ids)

    def filter(self, query, column):
        return query if self.all else query.filter(column.in_(self.ids or {None}))


def require_permission_somewhere(*keys: str):
    """Dependency factory: 403 unless the caller holds one of ``keys`` on at least one
    server; returns the PermittedServers (where any of them is held) to filter by."""

    def _dep(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
        session: Annotated[Session, Depends(get_db_session)],
    ) -> PermittedServers:
        from uuid import UUID as _UUID

        from apps.api.app.core.permissions import access_of
        from apps.api.app.models.game_server import GameServer

        user = _user_from_credentials(credentials, session)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required")
        if not (user.is_admin or user.is_moderator):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
        access = access_of(user)
        if any(access.holds_everywhere(k) for k in keys):
            return PermittedServers(True, set())
        all_ids = [i for (i,) in session.query(GameServer.id).all()]
        ids = {_UUID(i) for k in keys for i in access.servers_with(k, all_ids)}
        if not ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {' / '.join(keys)}")
        return PermittedServers(False, ids)

    return _dep
