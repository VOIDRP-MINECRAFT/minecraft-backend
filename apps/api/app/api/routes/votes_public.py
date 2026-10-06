"""Monitoring sites call this when a player votes for a server (core/votes.py)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import votes
from apps.api.app.db import get_db_session
from apps.api.app.models.game_server import GameServer

router = APIRouter(prefix="/votes", tags=["votes"])


@router.api_route("/{slug}/{provider}", methods=["GET", "POST"], response_class=PlainTextResponse)
async def vote(slug: str, provider: str, request: Request, session: Annotated[Session, Depends(get_db_session)]) -> PlainTextResponse:
    params: dict[str, str] = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update({k: str(v) for k, v in form.items()})
        except Exception:  # noqa: BLE001 — a JSON body instead of a form
            try:
                body = await request.json()
                if isinstance(body, dict):
                    params.update({k: str(v) for k, v in body.items()})
            except Exception:  # noqa: BLE001
                pass
    server = session.scalar(select(GameServer).where(GameServer.slug == slug.lower()))
    if server is None:
        return PlainTextResponse("unknown server", status_code=404)
    try:
        text = votes.handle(session, server, provider.lower(), params, request.client.host if request.client else None)
    except votes.VoteRejected as exc:
        return PlainTextResponse(str(exc), status_code=403)
    return PlainTextResponse(text)
