from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.models.game_server import GameServer
from apps.api.app.repositories.game_server_repository import GameServerRepository


def require_game_server(
    session: Annotated[Session, Depends(get_db_session)],
    x_game_auth_secret: Annotated[str | None, Header(alias="X-Game-Auth-Secret")] = None,
    x_server_slug: Annotated[str | None, Header(alias="X-Server-Slug")] = None,
) -> GameServer:
    """Authenticate a game server by its per-server ``X-Game-Auth-Secret``.

    Returns the matched :class:`GameServer` so callers can scope data by
    ``server.id``. Backward compatible: if the secret equals the legacy global
    ``GAME_AUTH_SHARED_SECRET`` it maps to the default server.
    """
    repo = GameServerRepository(session)

    server = repo.get_by_secret(x_game_auth_secret) if x_game_auth_secret else None

    # Legacy fallback: global shared secret -> default server.
    if server is None and x_game_auth_secret:
        settings = get_settings()
        if settings.game_auth_shared_secret and hmac.compare_digest(
            x_game_auth_secret, settings.game_auth_shared_secret
        ):
            server = repo.get_default()

    if server is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid game auth secret",
        )

    # Optional explicit slug must agree with the secret's server.
    if x_server_slug and server.slug != x_server_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Server slug does not match auth secret",
        )

    return server


def require_game_auth_secret(
    _server: Annotated[GameServer, Depends(require_game_server)],
) -> None:
    """Backward-compatible guard for routes that only need validation.

    Existing routes use ``Depends(require_game_auth_secret)`` and ignore the
    return value; they keep working unchanged.
    """
    return None
