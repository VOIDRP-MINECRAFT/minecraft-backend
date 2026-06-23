from __future__ import annotations

from pydantic import BaseModel, Field


class LauncherPreferencesRead(BaseModel):
    disabled_mods: list[str] = Field(default_factory=list)
    config_files: dict[str, str] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class LauncherModPrefsUpdate(BaseModel):
    disabled_mods: list[str] = Field(default_factory=list)


class LauncherConfigFileRead(BaseModel):
    path: str
    found: bool = False
    content_b64: str | None = None


class LauncherConfigFileUpdate(BaseModel):
    path: str
    content_b64: str
