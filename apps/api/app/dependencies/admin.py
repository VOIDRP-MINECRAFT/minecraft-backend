from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core.security import decode_access_token
from apps.api.app.db import get_db_session
from apps.api.app.models.user import User

_optional_bearer = HTTPBearer(auto_error=False)


def require_admin_api_secret(
    x_admin_api_secret: Annotated[str | None, Header(alias="X-Admin-Api-Secret")] = None,
) -> None:
    settings = get_settings()
    if not x_admin_api_secret or x_admin_api_secret != settings.admin_api_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin api secret",
        )


def get_current_admin_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required")

    try:
        payload = decode_access_token(credentials.credentials)
        from uuid import UUID
        user = session.get(User, UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User unavailable")

    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    return user


def require_admin_access(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    """Accepts either X-Admin-Api-Secret header or a JWT from an is_admin user."""
    settings = get_settings()
    secret = request.headers.get("X-Admin-Api-Secret")

    if secret:
        if secret == settings.admin_api_secret:
            return
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin api secret")

    if credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            from uuid import UUID
            user = session.get(User, UUID(payload["sub"]))
            if user and user.is_active and user.is_admin:
                return
        except (jwt.PyJWTError, KeyError, ValueError):
            pass

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required")