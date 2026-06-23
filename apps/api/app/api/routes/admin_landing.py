from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_admin_access
from apps.api.app.models.landing_screenshot import LandingScreenshot

router = APIRouter(
    prefix="/admin/landing",
    tags=["admin", "landing"],
    dependencies=[Depends(require_admin_access)],
)

_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
_MAX_BYTES = 12 * 1024 * 1024  # 12 MB
_MAX_WIDTH = 1920


def _screenshot_url(storage_key: str) -> str:
    return f"{get_settings().media_public_base_url}/{storage_key}"


def _row_to_dict(row: LandingScreenshot) -> dict:
    return {
        "id": str(row.id),
        "url": _screenshot_url(row.storage_key),
        "display_order": row.display_order,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/screenshots")
def list_screenshots(session: Annotated[Session, Depends(get_db_session)]) -> list[dict]:
    rows = session.execute(
        select(LandingScreenshot).order_by(LandingScreenshot.display_order, LandingScreenshot.created_at)
    ).scalars().all()
    return [_row_to_dict(r) for r in rows]


@router.post("/screenshots", status_code=status.HTTP_201_CREATED)
async def upload_screenshot(
    session: Annotated[Session, Depends(get_db_session)],
    file: UploadFile = File(...),
) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="file too large (max 12 MB)")

    try:
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if (img.format or "").upper() not in _ALLOWED_FORMATS:
                raise HTTPException(status_code=400, detail="only png, jpeg, webp allowed")
            working = img.convert("RGB")
            if working.width > _MAX_WIDTH:
                ratio = _MAX_WIDTH / working.width
                working = working.resize(
                    (int(working.width * ratio), int(working.height * ratio)),
                    Image.Resampling.LANCZOS,
                )
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="not a valid image")

    settings = get_settings()
    asset_id = uuid4()
    rel_dir = Path("landing") / "screenshots"
    filename = f"{asset_id}.webp"
    storage_key = str((rel_dir / filename).as_posix())

    abs_dir = Path(settings.media_storage_root) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    working.save(abs_dir / filename, format="WEBP", quality=88, method=4)

    max_order_row = session.execute(
        select(LandingScreenshot.display_order).order_by(LandingScreenshot.display_order.desc()).limit(1)
    ).scalar()
    next_order = (max_order_row or 0) + 1

    row = LandingScreenshot(storage_key=storage_key, display_order=next_order)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _row_to_dict(row)


@router.delete("/screenshots/{screenshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_screenshot(
    screenshot_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    row = session.get(LandingScreenshot, screenshot_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")

    abs_path = Path(get_settings().media_storage_root) / row.storage_key
    abs_path.unlink(missing_ok=True)

    session.delete(row)
    session.commit()
