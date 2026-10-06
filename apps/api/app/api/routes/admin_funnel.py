"""«Воронка новичка»: от регистрации до игры через неделю (core/funnel.py)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import funnel
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission
from apps.api.app.models.game_server import GameServer

router = APIRouter(prefix="/admin/funnel", tags=["admin", "funnel"],
                   dependencies=[Depends(require_permission("players.view"))])


@router.get("")
def get_funnel(
    session: Annotated[Session, Depends(get_db_session)],
    server_slug: Annotated[str | None, Query(max_length=64)] = None,
    source: Annotated[str | None, Query(pattern=r"^[a-z0-9_.:\-]{1,64}$")] = None,
    weeks: Annotated[int, Query(ge=2, le=52)] = 12,
) -> dict:
    server_id = None
    if server_slug:
        server = session.scalar(select(GameServer).where(GameServer.slug == server_slug))
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")
        server_id = server.id
    return funnel.build(session, server_id=server_id, source=source, weeks=weeks)
