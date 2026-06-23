from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image
from fastapi import UploadFile
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models.nation import Nation
from apps.api.app.models.user import User
from apps.api.app.services.nation_activity_service import NationActivityService
from apps.api.app.services.nation_service import NationPermissionError, NationService

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


class NationMediaValidationError(Exception): ...


class NationMediaService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.nation_service = NationService(session)
        self.activity_service = NationActivityService(session)

    async def save_nation_asset(self, current_user: User, slot: str, upload: UploadFile) -> Nation:
        nation = self._require_manageable_nation(current_user)
        raw = await upload.read()
        rules = self._slot_rules(slot)
        if upload.content_type not in ALLOWED_MIME_TYPES:
            raise NationMediaValidationError("Only PNG, JPEG and WEBP images are allowed")
        if len(raw) > rules["max_bytes"]:
            raise NationMediaValidationError("Uploaded file is too large for this slot")
        try:
            image = Image.open(BytesIO(raw))
            image.load()
        except Exception as exc:
            raise NationMediaValidationError("Failed to read image file") from exc
        width, height = image.size
        if width < rules["min_width"] or height < rules["min_height"]:
            raise NationMediaValidationError("Image resolution is too small")

        output_dir = Path(self.settings.media_storage_root) / "nations" / str(nation.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        full_name = f"{slot}_full.webp"
        preview_name = f"{slot}_preview.webp"
        full_image = self._prepare_variant(image, rules["full_size"])
        preview_image = self._prepare_variant(image, rules["preview_size"])
        full_image.save(output_dir / full_name, format="WEBP", quality=90, method=6)
        preview_image.save(output_dir / preview_name, format="WEBP", quality=86, method=6)

        nation_prefix = f"{self.settings.media_public_base_url}/nations/{nation.id}"
        if slot == "icon":
            nation.icon_url = f"{nation_prefix}/{full_name}"
            nation.icon_preview_url = f"{nation_prefix}/{preview_name}"
        elif slot == "banner":
            nation.banner_url = f"{nation_prefix}/{full_name}"
            nation.banner_preview_url = f"{nation_prefix}/{preview_name}"
        elif slot == "background":
            nation.background_url = f"{nation_prefix}/{full_name}"
            nation.background_preview_url = f"{nation_prefix}/{preview_name}"
        else:
            raise NationMediaValidationError("Unknown nation asset slot")

        self.activity_service.record(
            nation_id=nation.id,
            event_type="asset_updated",
            actor_user_id=current_user.id,
            message=f"Обновлён слот {slot}.",
            metadata={"slot": slot},
        )
        self.session.commit()
        return nation

    def delete_nation_asset(self, current_user: User, slot: str) -> Nation:
        nation = self._require_manageable_nation(current_user)
        output_dir = Path(self.settings.media_storage_root) / "nations" / str(nation.id)
        names = {
            "icon": ("icon_full.webp", "icon_preview.webp"),
            "banner": ("banner_full.webp", "banner_preview.webp"),
            "background": ("background_full.webp", "background_preview.webp"),
        }
        if slot not in names:
            raise NationMediaValidationError("Unknown nation asset slot")
        for filename in names[slot]:
            try:
                os.remove(output_dir / filename)
            except FileNotFoundError:
                pass
        if slot == "icon":
            nation.icon_url = None
            nation.icon_preview_url = None
        elif slot == "banner":
            nation.banner_url = None
            nation.banner_preview_url = None
        elif slot == "background":
            nation.background_url = None
            nation.background_preview_url = None

        self.activity_service.record(
            nation_id=nation.id,
            event_type="asset_deleted",
            actor_user_id=current_user.id,
            message=f"Удалён слот {slot}.",
            metadata={"slot": slot},
        )
        self.session.commit()
        return nation

    def _require_manageable_nation(self, current_user: User) -> Nation:
        nation = self.nation_service._find_nation_for_user(current_user.id)
        if nation is None:
            raise NationPermissionError("user is not in a nation")
        membership = next((item for item in nation.members if item.user_id == current_user.id), None)
        if membership is None or membership.role not in {"leader", "officer"}:
            raise NationPermissionError("not enough permissions to manage nation assets")
        return nation

    def _prepare_variant(self, image: Image.Image, size: tuple[int, int]) -> Image.Image:
        prepared = image.convert("RGB").copy()
        prepared.thumbnail(size, Image.LANCZOS)
        canvas = Image.new("RGB", size, color=(15, 23, 42))
        x = max((size[0] - prepared.width) // 2, 0)
        y = max((size[1] - prepared.height) // 2, 0)
        canvas.paste(prepared, (x, y))
        return canvas

    def _slot_rules(self, slot: str) -> dict:
        if slot == "icon":
            return {"max_bytes": 512 * 1024, "min_width": 256, "min_height": 256, "full_size": (512, 512), "preview_size": (128, 128)}
        if slot == "banner":
            return {"max_bytes": 2 * 1024 * 1024, "min_width": 1280, "min_height": 320, "full_size": (1600, 400), "preview_size": (800, 200)}
        if slot == "background":
            return {"max_bytes": 3 * 1024 * 1024, "min_width": 1600, "min_height": 900, "full_size": (1920, 1080), "preview_size": (960, 540)}
        raise NationMediaValidationError("Unknown nation asset slot")
