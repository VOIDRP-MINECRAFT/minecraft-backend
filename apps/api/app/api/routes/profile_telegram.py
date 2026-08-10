from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.telegram import TelegramLinkToken
from apps.api.app.models.user import User
from apps.api.app.schemas.telegram import TelegramLinkRequest, TelegramLinkStatus

router = APIRouter(prefix="/profile/telegram", tags=["profile", "telegram"])


def _status(user: User) -> TelegramLinkStatus:
    return TelegramLinkStatus(
        linked=user.telegram_user_id is not None,
        telegram_username=user.telegram_username,
        telegram_user_id=user.telegram_user_id,
    )


@router.get("", response_model=TelegramLinkStatus)
def get_telegram_status(
    current_user: Annotated[User, Depends(get_current_user)],
) -> TelegramLinkStatus:
    return _status(current_user)


@router.post("/link", response_model=TelegramLinkStatus)
def link_telegram(
    payload: TelegramLinkRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> TelegramLinkStatus:
    """Consume a one-time token issued by the bot and bind the Telegram account
    to the currently authenticated user."""
    token = session.scalar(
        select(TelegramLinkToken).where(TelegramLinkToken.token == payload.token)
    )
    if token is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid link code")
    now = datetime.now(timezone.utc)
    expires = token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if token.used_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Link code already used")
    if expires < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Link code expired")

    # This Telegram account must not already be bound to a different user.
    existing = session.scalar(
        select(User).where(
            User.telegram_user_id == token.telegram_user_id, User.id != current_user.id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Telegram account is already linked to another user",
        )

    current_user.telegram_user_id = token.telegram_user_id
    current_user.telegram_username = token.telegram_username
    token.used_at = now
    session.commit()
    session.refresh(current_user)
    return _status(current_user)


@router.delete("", response_model=TelegramLinkStatus)
def unlink_telegram(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> TelegramLinkStatus:
    current_user.telegram_user_id = None
    current_user.telegram_username = None
    session.commit()
    session.refresh(current_user)
    return _status(current_user)
