"""Reactive in-game notifications.

- ``/game-ui/notifications`` — WebGUI HUD (webgui token): poll the feed, dismiss.
- ``/game-sync/notifications`` — plugin-facing (game-auth secret): push a
  notification to a player by nickname (battle-pass award, join request, votes…).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.dependencies.webgui_auth import get_webgui_player
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.services.notification_service import NotificationService

router = APIRouter(prefix="/game-ui/notifications", tags=["game-ui", "notifications"])
plugin_router = APIRouter(prefix="/game-sync/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    title: str
    body: str | None
    icon: str | None
    accent: str | None
    action_type: str | None
    action_payload: str | None
    action_label: str | None
    seen_at: datetime | None
    created_at: datetime


class NotificationFeed(BaseModel):
    items: list[NotificationOut]


class NotificationPush(BaseModel):
    minecraft_nickname: str
    type: str = "info"
    title: str = Field(min_length=1, max_length=160)
    body: str | None = None
    icon: str | None = None
    accent: str | None = None
    action_type: str | None = None       # route | command
    action_payload: str | None = None
    action_label: str | None = None


# ── WebGUI (HUD) ──────────────────────────────────────────────────────────────

@router.get("", response_model=NotificationFeed)
def get_feed(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NotificationFeed:
    svc = NotificationService(db, server.id)
    items = svc.feed(player.user_id)
    out = [NotificationOut.model_validate(n) for n in items]   # serialize before commit
    # One-shot: mark them seen so they flash exactly once (kept in DB for history).
    if items:
        svc.mark_seen(player.user_id, [n.id for n in items])
        db.commit()
    return NotificationFeed(items=out)


@router.get("/history", response_model=NotificationFeed)
def get_history(
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NotificationFeed:
    """The in-game notification center: recent undismissed notifications, does not mark seen."""
    svc = NotificationService(db, server.id)
    items = svc.history(player.user_id)
    return NotificationFeed(items=[NotificationOut.model_validate(n) for n in items])


@router.post("/{notification_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(
    notification_id: UUID,
    player: Annotated[PlayerAccount, Depends(get_webgui_player)],
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> None:
    NotificationService(db, server.id).dismiss(notification_id, player.user_id)
    db.commit()


# ── Plugin push (game-auth secret) ────────────────────────────────────────────

@plugin_router.post("", status_code=status.HTTP_201_CREATED)
def push_notification(
    payload: NotificationPush,
    db: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(require_game_server)],
) -> dict:
    note = NotificationService(db, server.id).create_for_nick(
        payload.minecraft_nickname,
        type=payload.type,
        title=payload.title,
        body=payload.body,
        icon=payload.icon,
        accent=payload.accent,
        action_type=payload.action_type,
        action_payload=payload.action_payload,
        action_label=payload.action_label,
    )
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player account not found")
    db.commit()
    return {"id": str(note.id)}
