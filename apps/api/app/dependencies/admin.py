from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
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
    return user


def caller_permissions(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> set[str]:
    """Effective permission set of the caller.

    Full admins get every key; moderators get their granted subset. Raises
    401/403 if the caller is not staff at all.
    """
    user = _user_from_credentials(credentials, session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required")
    if not (user.is_admin or user.is_moderator):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
    return resolve_user_permissions(user)


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