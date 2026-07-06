"""Battle Pass game-ui endpoints — view player progress from the WebGUI browser."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.battlepass import BattlePassPublicProfileResponse
from apps.api.app.services.battlepass_service import BattlePassService

router = APIRouter(prefix="/game-ui/battlepass", tags=["game-ui", "battlepass"])


def _service(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> BattlePassService:
    return BattlePassService(session=db, server_id=server.id)


@router.get("/status", response_model=BattlePassPublicProfileResponse)
def get_battlepass_status(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    svc: Annotated[BattlePassService, Depends(_service)],
) -> BattlePassPublicProfileResponse:
    profile = svc.get_public_profile_by_nick(player.minecraft_nickname)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Прогресс Battle Pass не найден. Зайди в игру, чтобы инициализировать данные.",
        )
    return profile
