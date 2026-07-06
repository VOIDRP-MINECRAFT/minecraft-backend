from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.schemas.launcher_dashboard import LauncherDashboardRead
from apps.api.app.services.launcher_dashboard_service import LauncherDashboardService

router = APIRouter(prefix="/launcher", tags=["launcher-dashboard"])


def get_launcher_dashboard_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> LauncherDashboardService:
    return LauncherDashboardService(session, server.id)


@router.get("/me/dashboard", response_model=LauncherDashboardRead)
def get_my_launcher_dashboard(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LauncherDashboardService, Depends(get_launcher_dashboard_service)],
) -> LauncherDashboardRead:
    return service.get_for_user(current_user)
