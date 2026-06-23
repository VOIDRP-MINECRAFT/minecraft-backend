from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.user import User
from apps.api.app.schemas.launcher_prefs import (
    LauncherConfigFileRead,
    LauncherConfigFileUpdate,
    LauncherModPrefsUpdate,
    LauncherPreferencesRead,
)
from apps.api.app.services.launcher_prefs_service import LauncherPrefsService

router = APIRouter(prefix="/launcher", tags=["launcher-prefs"])


def get_prefs_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> LauncherPrefsService:
    return LauncherPrefsService(session)


@router.get("/me/prefs", response_model=LauncherPreferencesRead)
def get_my_prefs(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LauncherPrefsService, Depends(get_prefs_service)],
) -> LauncherPreferencesRead:
    return service.get(current_user)


@router.put("/me/prefs/mods", response_model=LauncherPreferencesRead)
def update_mod_prefs(
    data: LauncherModPrefsUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LauncherPrefsService, Depends(get_prefs_service)],
) -> LauncherPreferencesRead:
    return service.save_mods(current_user, data)


@router.get("/me/prefs/config", response_model=LauncherConfigFileRead)
def get_config_file(
    path: Annotated[str, Query(description="Relative path, e.g. options.txt")],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LauncherPrefsService, Depends(get_prefs_service)],
) -> LauncherConfigFileRead:
    return service.get_config_file(current_user, path)


@router.put("/me/prefs/config")
def save_config_file(
    data: LauncherConfigFileUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LauncherPrefsService, Depends(get_prefs_service)],
) -> dict:
    try:
        service.save_config_file(current_user, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
