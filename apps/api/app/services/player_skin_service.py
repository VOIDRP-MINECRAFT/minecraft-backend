from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_skin import PlayerSkin
from apps.api.app.models.user import User
from apps.api.app.schemas.account import PlayerSkinRead
from apps.api.app.services.redis_cache_service import RedisCacheService
from apps.api.app.utils.normalization import normalize_minecraft_nickname

_ALLOWED_DIMENSIONS = {(64, 64), (64, 32)}


class PlayerSkinValidationError(Exception):
    pass


class PlayerSkinService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.cache = RedisCacheService()

    def get_for_user(self, current_user: User) -> PlayerSkin | None:
        return self.session.execute(
            select(PlayerSkin).where(PlayerSkin.user_id == current_user.id)
        ).scalar_one_or_none()

    def get_for_minecraft_nickname(self, minecraft_nickname: str) -> tuple[PlayerAccount | None, PlayerSkin | None]:
        _, normalized = normalize_minecraft_nickname(minecraft_nickname)
        player_account = self.session.execute(
            select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == normalized)
        ).scalar_one_or_none()

        if player_account is None:
            return None, None

        skin = self.session.execute(
            select(PlayerSkin).where(PlayerSkin.user_id == player_account.user_id)
        ).scalar_one_or_none()
        return player_account, skin

    def to_read(self, skin: PlayerSkin | None) -> PlayerSkinRead:
        if skin is None:
            return PlayerSkinRead(has_skin=False)

        return PlayerSkinRead(
            has_skin=True,
            model_variant=skin.model_variant,
            skin_url=skin.original_url,
            head_preview_url=skin.head_preview_url,
            body_preview_url=skin.body_preview_url,
            width=skin.width,
            height=skin.height,
            sha256=skin.sha256,
            updated_at=skin.updated_at,
        )

    async def save_for_user(
        self,
        *,
        current_user: User,
        upload: UploadFile,
        model_variant: str | None,
    ) -> PlayerSkin:
        raw = await upload.read()
        if not raw:
            raise PlayerSkinValidationError("Файл пустой.")

        max_bytes = int(getattr(self.settings, "player_skin_max_bytes", 3 * 1024 * 1024))
        if len(raw) > max_bytes:
            raise PlayerSkinValidationError("Скин слишком большой. Используй PNG до 3 MB.")

        try:
            with Image.open(BytesIO(raw)) as source_image:
                source_image.load()
                image_format = (source_image.format or "").upper()
                if image_format != "PNG":
                    raise PlayerSkinValidationError("Поддерживается только PNG.")
                width, height = source_image.size
                if (width, height) not in _ALLOWED_DIMENSIONS:
                    raise PlayerSkinValidationError("Размер скина должен быть 64x64 или 64x32.")
                skin_sheet = source_image.convert("RGBA")
        except UnidentifiedImageError as exc:
            raise PlayerSkinValidationError("Файл не распознан как изображение PNG.") from exc

        safe_variant = (model_variant or "").strip().lower() or "classic"
        if safe_variant not in {"classic", "slim"}:
            raise PlayerSkinValidationError("Вариант скина должен быть classic или slim.")

        sha256 = hashlib.sha256(raw).hexdigest()
        current = self.get_for_user(current_user)

        relative_dir = Path("skins") / str(current_user.id)
        absolute_dir = Path(self.settings.media_storage_root) / relative_dir
        absolute_dir.mkdir(parents=True, exist_ok=True)

        asset_id = uuid4()
        original_name = f"{asset_id}.png"
        head_name = f"{asset_id}_head.png"
        body_name = f"{asset_id}_body.png"

        original_path = absolute_dir / original_name
        head_path = absolute_dir / head_name
        body_path = absolute_dir / body_name

        original_path.write_bytes(raw)
        head_preview = self._build_head_preview(skin_sheet)
        body_preview = self._build_body_preview(skin_sheet)
        head_preview.save(head_path, format="PNG", optimize=True)
        body_preview.save(body_path, format="PNG", optimize=True)

        original_relative = str((relative_dir / original_name).as_posix())
        head_relative = str((relative_dir / head_name).as_posix())
        body_relative = str((relative_dir / body_name).as_posix())

        if current is None:
            current = PlayerSkin(
                user_id=current_user.id,
                model_variant=safe_variant,
                mime_type="image/png",
                file_size_bytes=len(raw),
                width=width,
                height=height,
                sha256=sha256,
                original_storage_key=original_relative,
                original_url=self._public_url(original_relative),
                head_preview_storage_key=head_relative,
                head_preview_url=self._public_url(head_relative),
                body_preview_storage_key=body_relative,
                body_preview_url=self._public_url(body_relative),
            )
            self.session.add(current)
        else:
            self._delete_if_exists(current.original_storage_key)
            self._delete_if_exists(current.head_preview_storage_key)
            self._delete_if_exists(current.body_preview_storage_key)

            current.model_variant = safe_variant
            current.mime_type = "image/png"
            current.file_size_bytes = len(raw)
            current.width = width
            current.height = height
            current.sha256 = sha256
            current.original_storage_key = original_relative
            current.original_url = self._public_url(original_relative)
            current.head_preview_storage_key = head_relative
            current.head_preview_url = self._public_url(head_relative)
            current.body_preview_storage_key = body_relative
            current.body_preview_url = self._public_url(body_relative)

        self.session.commit()
        self.session.refresh(current)
        self._invalidate_skin_cache(current_user)
        return current

    def delete_for_user(self, *, current_user: User) -> None:
        skin = self.get_for_user(current_user)
        if skin is None:
            return

        self._delete_if_exists(skin.original_storage_key)
        self._delete_if_exists(skin.head_preview_storage_key)
        self._delete_if_exists(skin.body_preview_storage_key)
        self.session.delete(skin)
        self.session.commit()
        self._invalidate_skin_cache(current_user)

    def _invalidate_skin_cache(self, current_user: User) -> None:
        if current_user.player_account is not None:
            normalized = (current_user.player_account.minecraft_nickname_normalized or "").strip().lower()
            if normalized:
                self.cache.delete(f"player_skin:{normalized}")
                self.cache.delete(f"player_access:{normalized}")
        self.cache.delete(f"launcher_dashboard:user:{current_user.id}")

    def _public_url(self, relative_path: str) -> str:
        return f"{self.settings.media_public_base_url}/{relative_path}"

    def _delete_if_exists(self, relative_path: str | None) -> None:
        if not relative_path:
            return
        absolute = Path(self.settings.media_storage_root) / relative_path
        try:
            if absolute.exists():
                absolute.unlink()
        except OSError:
            pass

    def _build_head_preview(self, image: Image.Image) -> Image.Image:
        size = int(getattr(self.settings, "player_skin_head_preview_size", 256))
        canvas = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        base_face = image.crop((8, 8, 16, 16))
        canvas.alpha_composite(base_face, (0, 0))
        if image.height >= 32:
            overlay = image.crop((40, 8, 48, 16))
            canvas.alpha_composite(overlay, (0, 0))
        return canvas.resize((size, size), Image.Resampling.NEAREST)

    def _build_body_preview(self, image: Image.Image) -> Image.Image:
        body_width = int(getattr(self.settings, "player_skin_body_preview_width", 176))
        body_height = int(getattr(self.settings, "player_skin_body_preview_height", 320))
        body = Image.new("RGBA", (16, 32), (0, 0, 0, 0))

        body.alpha_composite(image.crop((8, 8, 16, 16)), (4, 0))
        if image.height >= 32:
            body.alpha_composite(image.crop((40, 8, 48, 16)), (4, 0))

        body.alpha_composite(image.crop((20, 20, 28, 32)), (4, 8))
        if image.height >= 64:
            body.alpha_composite(image.crop((20, 36, 28, 48)), (4, 8))

        body.alpha_composite(image.crop((44, 20, 48, 32)), (0, 8))
        if image.height >= 64:
            body.alpha_composite(image.crop((44, 36, 48, 48)), (0, 8))

        if image.height >= 64:
            left_arm = image.crop((36, 52, 40, 64))
            left_arm_overlay = image.crop((52, 52, 56, 64))
        else:
            left_arm = ImageOps.mirror(image.crop((44, 20, 48, 32)))
            left_arm_overlay = ImageOps.mirror(image.crop((44, 20, 48, 32)).copy())
        body.alpha_composite(left_arm, (12, 8))
        if image.height >= 64:
            body.alpha_composite(left_arm_overlay, (12, 8))

        body.alpha_composite(image.crop((4, 20, 8, 32)), (4, 20))
        if image.height >= 64:
            body.alpha_composite(image.crop((4, 36, 8, 48)), (4, 20))

        if image.height >= 64:
            left_leg = image.crop((20, 52, 24, 64))
            left_leg_overlay = image.crop((4, 52, 8, 64))
        else:
            left_leg = ImageOps.mirror(image.crop((4, 20, 8, 32)))
            left_leg_overlay = ImageOps.mirror(image.crop((4, 20, 8, 32)).copy())
        body.alpha_composite(left_leg, (8, 20))
        if image.height >= 64:
            body.alpha_composite(left_leg_overlay, (8, 20))

        return body.resize((body_width, body_height), Image.Resampling.NEAREST)
