from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_admin_user
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_feedback import FeedbackType, PlayerFeedback
from apps.api.app.models.user import User
from apps.api.app.schemas.player_feedback import (
    PlayerFeedbackCreate,
    PlayerFeedbackListResponse,
    PlayerFeedbackRead,
)

router = APIRouter(tags=["player-feedback"])


@router.post("/player-feedback/", status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: PlayerFeedbackCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    feedback = PlayerFeedback(
        user_id=current_user.id,
        type=FeedbackType(payload.type),
        title=payload.title,
        body=payload.body,
    )
    session.add(feedback)
    session.commit()
    return {"message": "Обращение отправлено", "id": str(feedback.id)}


@router.get("/admin/player-feedback/")
def list_feedback(
    _: Annotated[User, Depends(get_current_admin_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PlayerFeedbackListResponse:
    rows = session.execute(
        select(PlayerFeedback, User, PlayerAccount)
        .join(User, PlayerFeedback.user_id == User.id)
        .outerjoin(PlayerAccount, PlayerAccount.user_id == User.id)
        .order_by(PlayerFeedback.created_at.desc())
    ).all()

    items = [
        PlayerFeedbackRead(
            id=row.PlayerFeedback.id,
            type=str(row.PlayerFeedback.type),
            title=row.PlayerFeedback.title,
            body=row.PlayerFeedback.body,
            created_at=row.PlayerFeedback.created_at,
            user_login=row.User.site_login,
            user_nickname=row.PlayerAccount.minecraft_nickname if row.PlayerAccount else None,
        )
        for row in rows
    ]
    return PlayerFeedbackListResponse(items=items, total=len(items))


@router.delete("/admin/player-feedback/{feedback_id}")
def delete_feedback(
    feedback_id: UUID,
    _: Annotated[User, Depends(get_current_admin_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    feedback = session.get(PlayerFeedback, feedback_id)
    if not feedback:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    session.delete(feedback)
    session.commit()
    return {"message": "Deleted"}
