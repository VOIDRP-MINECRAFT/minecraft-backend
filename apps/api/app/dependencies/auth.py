from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from apps.api.app.core.security import decode_access_token
from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.models.user import User

bearer_scheme = HTTPBearer(auto_error=True)
optional_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=translate_user_message("Invalid access token payload"),
            )

        user = session.get(User, UUID(user_id))
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=translate_user_message("User is not available"),
            )

        return user
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate_user_message("Invalid or expired access token"),
        ) from exc



def get_optional_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(optional_bearer_scheme),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> User | None:
    if credentials is None:
        return None

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            return None

        user = session.get(User, UUID(user_id))
        if user is None or not user.is_active:
            return None

        return user
    except jwt.PyJWTError:
        return None


def device_from_token(token: str, session: Session):
    """The sign-in (auth_devices row) an access token belongs to, or None (a token from
    before devices existed, or a signed-out device)."""
    from apps.api.app.models.auth_device import AuthDevice

    try:
        sid = decode_access_token(token).get("sid")
    except jwt.PyJWTError:
        return None
    if not sid:
        return None
    try:
        device = session.get(AuthDevice, UUID(sid))
    except ValueError:
        return None
    return device if device is not None and device.revoked_at is None else None


def get_current_device(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
):
    device = device_from_token(credentials.credentials, session)
    if device is None or device.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_revoked")
    return device
