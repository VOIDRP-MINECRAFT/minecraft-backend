from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models.telegram import TelegramLinkToken
from apps.api.app.models.user import User

_TTL = timedelta(minutes=10)


def user_by_telegram_id(session: Session, telegram_user_id: int) -> User | None:
    return session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))


def issue_link_token(session: Session, telegram_user_id: int, telegram_username: str | None) -> str:
    """Create a one-time link nonce for this Telegram user and return the link URL."""
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(24)
    session.add(TelegramLinkToken(
        token=token,
        telegram_user_id=telegram_user_id,
        telegram_username=telegram_username,
        created_at=now,
        expires_at=now + _TTL,
    ))
    session.flush()
    base = get_settings().website_base_url.rstrip("/")
    return f"{base}/link-telegram?token={token}"
