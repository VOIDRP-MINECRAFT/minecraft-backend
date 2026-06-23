from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from apps.api.app.config import get_settings


def require_game_auth_secret(
    x_game_auth_secret: Annotated[str | None, Header(alias="X-Game-Auth-Secret")] = None,
) -> None:
    settings = get_settings()
    if not x_game_auth_secret or not hmac.compare_digest(
        x_game_auth_secret, settings.game_auth_shared_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid game auth secret",
        )
