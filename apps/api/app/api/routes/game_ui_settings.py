"""Account-level in-game settings: webgui read/write + plugin read (game-auth)."""
from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_game_settings import PlayerGameSettings
from apps.api.app.services.notification_service import MUTABLE_NOTIFICATION_TYPES as MUTABLE_NOTIFICATIONS

router = APIRouter(prefix="/game-ui/settings", tags=["game-ui", "settings"])
plugin_router = APIRouter(prefix="/game-sync/player-settings", tags=["settings"])

_DEFAULTS = {"hud_auto_open": True, "muted_notifications": []}


def _read(row: PlayerGameSettings | None) -> dict:
    s = dict(_DEFAULTS)
    if row and isinstance(row.settings, dict):
        s.update(row.settings)
    s["hud_auto_open"] = bool(s.get("hud_auto_open", True))
    muted = s.get("muted_notifications") or []
    s["muted_notifications"] = [m for m in muted if m in MUTABLE_NOTIFICATIONS]
    return s


class SettingsOut(BaseModel):
    hud_auto_open: bool
    muted_notifications: list[str]
    mutable_notifications: list[str]


class SettingsPatch(BaseModel):
    hud_auto_open: bool | None = None
    muted_notifications: list[str] | None = None


@router.get("", response_model=SettingsOut)
def get_settings(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> SettingsOut:
    row = db.execute(
        select(PlayerGameSettings).where(
            PlayerGameSettings.server_id == server.id, PlayerGameSettings.user_id == player.user_id
        )
    ).scalar_one_or_none()
    s = _read(row)
    return SettingsOut(**s, mutable_notifications=sorted(MUTABLE_NOTIFICATIONS))


@router.patch("", response_model=SettingsOut)
def update_settings(
    payload: SettingsPatch,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> SettingsOut:
    row = db.execute(
        select(PlayerGameSettings).where(
            PlayerGameSettings.server_id == server.id, PlayerGameSettings.user_id == player.user_id
        )
    ).scalar_one_or_none()
    current = _read(row)
    if payload.hud_auto_open is not None:
        current["hud_auto_open"] = bool(payload.hud_auto_open)
    if payload.muted_notifications is not None:
        current["muted_notifications"] = [m for m in payload.muted_notifications if m in MUTABLE_NOTIFICATIONS]

    stored = {"hud_auto_open": current["hud_auto_open"], "muted_notifications": current["muted_notifications"]}
    if row is None:
        row = PlayerGameSettings(id=uuid4(), server_id=server.id, user_id=player.user_id, settings=stored)
        db.add(row)
    else:
        row.settings = stored
    db.commit()
    return SettingsOut(**current, mutable_notifications=sorted(MUTABLE_NOTIFICATIONS))


class PluginSettingsOut(BaseModel):
    hud_auto_open: bool


@plugin_router.get("", response_model=PluginSettingsOut)
def get_player_settings_for_plugin(
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
    nickname: str,
) -> PluginSettingsOut:
    """Plugin reads a player's settings by nickname (for HUD auto-open on join)."""
    account = db.execute(
        select(PlayerAccount).where(
            PlayerAccount.minecraft_nickname_normalized == nickname.strip().lower()
        )
    ).scalar_one_or_none()
    if account is None:
        return PluginSettingsOut(hud_auto_open=True)
    row = db.execute(
        select(PlayerGameSettings).where(
            PlayerGameSettings.server_id == server.id, PlayerGameSettings.user_id == account.user_id
        )
    ).scalar_one_or_none()
    return PluginSettingsOut(hud_auto_open=_read(row)["hud_auto_open"])
