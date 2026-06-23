from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import get_current_admin_user
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.mod_suggestion import ModSuggestion
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user import User
from apps.api.app.schemas.mod_suggestion import (
    ModSuggestionCreate,
    ModSuggestionListResponse,
    ModSuggestionRead,
)

router = APIRouter(tags=["mod-suggestions"])


@router.post("/mod-suggestions/", status_code=status.HTTP_201_CREATED)
def create_suggestion(
    payload: ModSuggestionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    suggestion = ModSuggestion(
        user_id=current_user.id,
        url=payload.url,
        comment=payload.comment,
    )
    session.add(suggestion)
    session.commit()
    return {"message": "Предложение отправлено", "id": str(suggestion.id)}


@router.get("/admin/mod-suggestions/")
def list_suggestions(
    _: Annotated[User, Depends(get_current_admin_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ModSuggestionListResponse:
    rows = session.execute(
        select(ModSuggestion, User, PlayerAccount)
        .join(User, ModSuggestion.user_id == User.id)
        .outerjoin(PlayerAccount, PlayerAccount.user_id == User.id)
        .order_by(ModSuggestion.created_at.desc())
    ).all()

    items = [
        ModSuggestionRead(
            id=row.ModSuggestion.id,
            url=row.ModSuggestion.url,
            comment=row.ModSuggestion.comment,
            created_at=row.ModSuggestion.created_at,
            user_login=row.User.site_login,
            user_nickname=row.PlayerAccount.minecraft_nickname if row.PlayerAccount else None,
        )
        for row in rows
    ]
    return ModSuggestionListResponse(items=items, total=len(items))


@router.delete("/admin/mod-suggestions/{suggestion_id}")
def delete_suggestion(
    suggestion_id: UUID,
    _: Annotated[User, Depends(get_current_admin_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    suggestion = session.get(ModSuggestion, suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    session.delete(suggestion)
    session.commit()
    return {"message": "Deleted"}
