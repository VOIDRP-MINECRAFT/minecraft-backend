from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.models.landing_screenshot import LandingScreenshot

router = APIRouter(prefix="/landing", tags=["landing"])


@router.get("/screenshots")
def list_public_screenshots(session: Annotated[Session, Depends(get_db_session)]) -> list[dict]:
    rows = session.execute(
        select(LandingScreenshot).order_by(LandingScreenshot.display_order, LandingScreenshot.created_at)
    ).scalars().all()
    base = get_settings().media_public_base_url
    return [
        {"id": str(r.id), "url": f"{base}/{r.storage_key}"}
        for r in rows
    ]
