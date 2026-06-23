from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.models.player_account import PlayerAccount


def _verify_token(token: str) -> str | None:
    """Verify HMAC-signed WebGUI token. Returns player nickname or None."""
    settings = get_settings()
    secret_b64 = settings.webgui_token_secret_base64
    if not secret_b64:
        return None
    try:
        secret = base64.b64decode(secret_b64)
    except Exception:
        return None

    dot = token.find(".")
    if dot <= 0 or dot >= len(token) - 1:
        return None

    try:
        payload_bytes = base64.urlsafe_b64decode(token[:dot] + "==")
        sig_bytes = base64.urlsafe_b64decode(token[dot + 1:] + "==")
    except Exception:
        return None

    expected = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig_bytes):
        return None

    try:
        payload = payload_bytes.decode("utf-8")
        version, player_name, exp_str = payload.split("|", 2)
    except (ValueError, UnicodeDecodeError):
        return None

    if version != "1" or not player_name:
        return None

    try:
        exp = int(exp_str)
    except ValueError:
        return None

    if time.time() > exp:
        return None

    return player_name


def get_webgui_player(
    webgui_token: Annotated[str, Query(alias="webgui_token")],
    db: Annotated[Session, Depends(get_db_session)],
) -> PlayerAccount:
    player_name = _verify_token(webgui_token)
    if player_name is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired webgui token",
        )

    player = (
        db.query(PlayerAccount)
        .filter(PlayerAccount.minecraft_nickname_normalized == player_name.lower())
        .first()
    )
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Player not found",
        )
    return player
