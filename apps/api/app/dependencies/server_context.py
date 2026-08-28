from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.core.permissions import HIDDEN_SERVERS_PERMISSION, resolve_user_permissions
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_optional_current_user
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.repositories.game_server_repository import GameServerRepository


def can_view_staff_only_servers(
    user: Annotated[User | None, Depends(get_optional_current_user)],
) -> bool:
    """Whether the caller may see ``staff_only`` servers in the public catalogue.

    Optional auth on purpose: anonymous visitors (and anyone whose token is
    stale) simply don't get the hidden servers — no 401, no error. Full admins
    pass through ``resolve_user_permissions``; moderators need
    ``servers.hidden.view``.
    """
    if user is None:
        return False
    return HIDDEN_SERVERS_PERMISSION in resolve_user_permissions(user)


def resolve_server(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[str | None, Query(description="Server slug")] = None,
    x_server_slug: Annotated[str | None, Header(alias="X-Server-Slug")] = None,
) -> GameServer:
    """Resolve the active server for a user-facing (site/launcher) request.

    Priority: ``?server=<slug>`` query param, then ``X-Server-Slug`` header,
    then the default server. Raises 404 for an unknown explicit slug.
    """
    slug = server or x_server_slug
    repo = GameServerRepository(session)

    if slug:
        found = repo.get_by_slug(slug)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown server '{slug}'",
            )
        return found

    default = repo.get_default()
    if default is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No default server configured",
        )
    return default
