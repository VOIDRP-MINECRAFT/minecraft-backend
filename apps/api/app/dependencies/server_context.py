from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.app.core.permissions import HIDDEN_SERVERS_PERMISSION
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_optional_current_user
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.repositories.game_server_repository import GameServerRepository


def can_view_staff_only_servers(
    user: Annotated[User | None, Depends(get_optional_current_user)],
):
    """Which ``staff_only`` servers the caller may see in the public catalogue — a
    predicate over a server.

    Optional auth on purpose: anonymous visitors (and anyone whose token is stale)
    simply don't get the hidden servers — no 401, no error. Seen by: full admins and
    holders of ``servers.hidden.view`` (every hidden server), and staff who hold any
    permission on that very server (an admin of a hidden server must find it).
    """
    if user is None:
        return lambda server: False
    from apps.api.app.core.permissions import SERVER_KEYS, access_of

    access = access_of(user)
    if access.holds_everywhere(HIDDEN_SERVERS_PERMISSION):
        return lambda server: True
    return lambda server: bool(access.on(server.id) & (SERVER_KEYS | {HIDDEN_SERVERS_PERMISSION}))


def maintenance_join_check(
    user: Annotated[User | None, Depends(get_optional_current_user)],
):
    """Predicate over a server: may the caller play on it during maintenance. Optional
    auth, like the hidden-server check — anonymous callers simply get False."""
    from apps.api.app.core.permissions import may_join_during_maintenance

    return lambda server: may_join_during_maintenance(user, server)


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


def resolve_webgui_server(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[str | None, Query(description="Server slug")] = None,
) -> GameServer:
    """Server for an in-game WebGUI (game-ui) request.

    A webgui token is signed only by the WebGUI mod of the main server (``PRIMARY_SERVER_SLUG``), so
    a page that names no server belongs to that one — not to the site's default server, which
    the admin may point at another server for visitors (that broke the main server's menu on
    05.10). ``X-Server-Slug`` is ignored here: it is the site's server picker state, not the
    game's. An explicit ``?server=`` still wins.
    """
    repo = GameServerRepository(session)
    if server:
        found = repo.get_by_slug(server)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown server '{server}'")
    else:
        found = repo.get_primary()
    if found is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No default server configured")
    return found
