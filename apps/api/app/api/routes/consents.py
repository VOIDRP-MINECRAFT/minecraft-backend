"""Consents on the site (/me/consents) and for the game server (/game-sync/consents/*)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.audit import client_ip
from apps.api.app.core.legal_documents import (
    DISTRIBUTION_MAP,
    DOC_DISTRIBUTION,
    DOC_OFFER,
    DOC_PERSONAL_DATA,
)
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_notification import PlayerNotification
from apps.api.app.models.user import User
from apps.api.app.services.consent_service import ConsentService
from apps.api.app.services.notification_service import NotificationService

router = APIRouter(tags=["consents"])


class DistributionChoice(BaseModel):
    profile: bool = False
    map: bool = False
    purchases: bool = False


class ConsentUpdateRequest(BaseModel):
    accept_offer: bool | None = None
    accept_personal_data: bool | None = None
    distribution: DistributionChoice | None = None


@router.get("/me/consents")
def my_consents(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    return ConsentService(db).status(user.id)


@router.post("/me/consents")
def update_my_consents(
    payload: ConsentUpdateRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    service = ConsentService(db)
    meta = {"source": "site", "ip": client_ip(request), "user_agent": request.headers.get("user-agent")}
    # Withdrawing the required consents is done by a written request (it deletes the account),
    # so here they can only be given.
    if payload.accept_offer is False or payload.accept_personal_data is False:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Отозвать согласие можно письмом на support@void-rp.ru — это приведёт к удалению аккаунта.")
    if payload.accept_offer:
        service.record(user.id, DOC_OFFER, granted=True, **meta)
    if payload.accept_personal_data:
        service.record(user.id, DOC_PERSONAL_DATA, granted=True, **meta)
    if payload.distribution is not None:
        service.record(user.id, DOC_DISTRIBUTION, granted=True, options=payload.distribution.model_dump(), **meta)
    db.commit()
    return service.status(user.id)


@router.get("/game-sync/consents/map-visible")
def map_visible_players(
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Nicknames (lowercase) of players who allowed their live position on the public map."""
    return {"nicknames": sorted(ConsentService(db).nicknames_allowing(DISTRIBUTION_MAP))}


class ConsentReminderRequest(BaseModel):
    nickname: str


REMIND_EVERY = timedelta(hours=72)


@router.post("/game-sync/consents/remind")
def remind_missing_consents(
    payload: ConsentReminderRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """Called on join: tells the plugin whether the player still has to accept the documents,
    and drops a HUD notification about it (not more than once per 72 hours)."""
    service = ConsentService(db)
    user_id, missing = service.missing_for_nickname(payload.nickname)
    if user_id is None or not missing:
        return {"pending": False}
    recent = db.execute(
        select(PlayerNotification.id).where(
            PlayerNotification.server_id == server.id,
            PlayerNotification.user_id == user_id,
            PlayerNotification.type == "legal",
            PlayerNotification.created_at >= datetime.now(timezone.utc) - REMIND_EVERY,
        ).limit(1)
    ).scalar_one_or_none()
    if recent is None:
        NotificationService(db, server.id).create(
            user_id=user_id,
            type="legal",
            title="Подтвердите условия на сайте",
            body="Мы обновили документы проекта. Зайдите на void-rp.ru, подтвердите новые условия и выберите, что показывать о вас другим игрокам.",
            icon="shield",
            accent="gold",
        )
        db.commit()
    return {"pending": True}
