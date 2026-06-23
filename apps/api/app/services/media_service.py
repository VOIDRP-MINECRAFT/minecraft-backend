from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models.media_asset import MediaAsset
from apps.api.app.models.player_public_profile import PlayerPublicProfile
from apps.api.app.models.user import User
from apps.api.app.services.public_profile_service import PublicProfileService

ALLOWED_FORMATS = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}


class MediaValidationError(Exception):
    pass


class ProfileMediaService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.profile_service = PublicProfileService(session)

    async def save_profile_asset(self, *, current_user: User, slot: str, upload: UploadFile) -> MediaAsset:
        profile = self.profile_service.ensure_profile_for_user(current_user)
        raw = await upload.read()
        limits = self._get_slot_limits(slot)

        if not raw:
            raise MediaValidationError("uploaded file is empty")
        if len(raw) > limits["max_bytes"]:
            raise MediaValidationError(f"file is too large for slot {slot}")

        try:
            with Image.open(BytesIO(raw)) as source_image:
                source_image.load()
                image_format = (source_image.format or "").upper()
                if image_format not in ALLOWED_FORMATS:
                    raise MediaValidationError("only png, jpeg and webp are allowed")

                width, height = source_image.size
                if width < limits["min_width"] or height < limits["min_height"]:
                    raise MediaValidationError("image is smaller than allowed minimum size")
                if width > limits["max_width"] or height > limits["max_height"]:
                    raise MediaValidationError("image is larger than allowed maximum size")

                working = source_image.convert("RGBA" if source_image.mode in {"RGBA", "LA", "P"} else "RGB")
                full_image = ImageOps.fit(working, limits["full_size"], method=Image.Resampling.LANCZOS)
                preview_image = ImageOps.fit(working, limits["preview_size"], method=Image.Resampling.LANCZOS)
        except UnidentifiedImageError as exc:
            raise MediaValidationError("file is not a valid image") from exc

        asset_id = uuid4()
        relative_dir = Path("profiles") / str(current_user.id) / slot
        full_name = f"{asset_id}.webp"
        preview_name = f"{asset_id}_preview.webp"

        absolute_dir = Path(self.settings.media_storage_root) / relative_dir
        absolute_dir.mkdir(parents=True, exist_ok=True)

        full_path = absolute_dir / full_name
        preview_path = absolute_dir / preview_name

        full_image.save(full_path, format="WEBP", quality=92, method=6)
        preview_image.save(preview_path, format="WEBP", quality=88, method=6)

        full_relative = str((relative_dir / full_name).as_posix())
        preview_relative = str((relative_dir / preview_name).as_posix())

        asset = MediaAsset(
            id=asset_id,
            owner_user_id=current_user.id,
            scope="profile",
            slot=slot,
            storage_key=full_relative,
            original_filename=upload.filename or f"{slot}.bin",
            mime_type="image/webp",
            file_size_bytes=len(raw),
            width=limits["full_size"][0],
            height=limits["full_size"][1],
            variants_json={
                "full": {
                    "path": full_relative,
                    "url": f"{self.settings.media_public_base_url}/{full_relative}",
                    "width": limits["full_size"][0],
                    "height": limits["full_size"][1],
                },
                "preview": {
                    "path": preview_relative,
                    "url": f"{self.settings.media_public_base_url}/{preview_relative}",
                    "width": limits["preview_size"][0],
                    "height": limits["preview_size"][1],
                },
            },
            is_active=True,
        )
        self.session.add(asset)
        self.session.flush()

        previous_asset = None
        if slot == "avatar":
            previous_asset = profile.avatar_asset
            profile.avatar_asset_id = asset.id
        elif slot == "banner":
            previous_asset = profile.banner_asset
            profile.banner_asset_id = asset.id
        elif slot == "background":
            previous_asset = profile.background_asset
            profile.background_asset_id = asset.id
        else:
            raise MediaValidationError("unsupported slot")

        if previous_asset is not None:
            previous_asset.is_active = False
            self._delete_asset_variants(previous_asset)

        self.session.commit()
        self.session.refresh(asset)
        return asset

    def remove_profile_asset(self, *, current_user: User, slot: str) -> None:
        profile = self.profile_service.ensure_profile_for_user(current_user)

        asset = None
        if slot == "avatar":
            asset = profile.avatar_asset
            profile.avatar_asset_id = None
        elif slot == "banner":
            asset = profile.banner_asset
            profile.banner_asset_id = None
        elif slot == "background":
            asset = profile.background_asset
            profile.background_asset_id = None
        else:
            raise MediaValidationError("unsupported slot")

        if asset is not None:
            asset.is_active = False
            self._delete_asset_variants(asset)

        self.session.commit()

    def _delete_asset_variants(self, asset: MediaAsset) -> None:
        variants = asset.variants_json or {}
        if not isinstance(variants, dict):
            return

        for item in variants.values():
            if not isinstance(item, dict):
                continue
            relative_path = item.get("path")
            if not relative_path:
                continue
            absolute_path = Path(self.settings.media_storage_root) / str(relative_path)
            try:
                if absolute_path.exists():
                    absolute_path.unlink()
            except OSError:
                pass

    def _get_slot_limits(self, slot: str) -> dict[str, object]:
        if slot == "avatar":
            return {
                "max_bytes": self.settings.profile_avatar_max_bytes,
                "min_width": self.settings.profile_avatar_min_width,
                "min_height": self.settings.profile_avatar_min_height,
                "max_width": self.settings.profile_avatar_max_width,
                "max_height": self.settings.profile_avatar_max_height,
                "full_size": (256, 256),
                "preview_size": (64, 64),
            }
        if slot == "banner":
            return {
                "max_bytes": self.settings.profile_banner_max_bytes,
                "min_width": self.settings.profile_banner_min_width,
                "min_height": self.settings.profile_banner_min_height,
                "max_width": self.settings.profile_banner_max_width,
                "max_height": self.settings.profile_banner_max_height,
                "full_size": (1600, 900),
                "preview_size": (800, 450),
            }
        if slot == "background":
            return {
                "max_bytes": self.settings.profile_background_max_bytes,
                "min_width": self.settings.profile_background_min_width,
                "min_height": self.settings.profile_background_min_height,
                "max_width": self.settings.profile_background_max_width,
                "max_height": self.settings.profile_background_max_height,
                "full_size": (1920, 1080),
                "preview_size": (960, 540),
            }
        raise MediaValidationError("unsupported slot")