from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.services.tiktok_service import resolve_and_record_click

router = APIRouter(prefix="/tiktok", tags=["tiktok-public"])

# Where to send users when a link is invalid/expired instead of an error page.
FALLBACK_URL = "https://www.tiktok.com/@voidrp.minecraft"


@router.get("/c/{campaign_id}/{minecraft_uuid}/{sig}")
def click_redirect(
    campaign_id: str,
    minecraft_uuid: str,
    sig: str,
    session: Annotated[Session, Depends(get_db_session)],
    n: Annotated[str | None, Query(description="player nickname (display only)")] = None,
) -> RedirectResponse:
    """Public tracked redirect.

    Records a one-time pending reward for the player (verified via HMAC), then
    302-redirects to the TikTok video. Invalid/old links fall back to the profile.
    """
    video_url = resolve_and_record_click(session, campaign_id, minecraft_uuid, n, sig)
    target = video_url or FALLBACK_URL
    # 302 so browsers don't cache the redirect (click is recorded each visit).
    return RedirectResponse(url=target, status_code=302)
