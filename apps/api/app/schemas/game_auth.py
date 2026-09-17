from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class GameAccountStateResponse(BaseModel):
    """What the login plugin needs to decide which window to show a joining player."""

    registered: bool
    minecraft_nickname: str
    account_active: bool = False
    email_verified: bool = False
    # Required documents this account has not accepted at the current version.
    consents_missing: list[str] = Field(default_factory=list)
    # Whether a distribution answer was ever given (the checkbox block is optional).
    distribution_answered: bool = False


class GameLoginRequest(BaseModel):
    minecraft_nickname: str = Field(min_length=3, max_length=16)
    password: str = Field(min_length=1, max_length=128)
    ip: str | None = Field(default=None, max_length=64)


class GameLoginResponse(BaseModel):
    user_id: UUID
    minecraft_nickname: str
    email_verified: bool
    consents_missing: list[str] = Field(default_factory=list)
    distribution_answered: bool = False


class GameRegisterRequest(BaseModel):
    """Registration from inside the game — same fields the site form asks for.

    The Minecraft nickname is the one the player is joining with, not a free text
    field, and it doubles as the site login so the window stays short.
    """

    minecraft_nickname: str = Field(min_length=3, max_length=16)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    password_repeat: str = Field(min_length=8, max_length=128)
    accept_offer: bool = False
    accept_personal_data: bool = False
    distribution_profile: bool = False
    distribution_map: bool = False
    distribution_purchases: bool = False
    ip: str | None = Field(default=None, max_length=64)

    @field_validator("password_repeat")
    @classmethod
    def validate_password_repeat(cls, value: str, info):
        password = info.data.get("password")
        if password is not None and value != password:
            raise ValueError("password_repeat must match password")
        return value


class GameConsentRequest(BaseModel):
    """Accepting the documents from the in-game window, for an account that predates them."""

    minecraft_nickname: str = Field(min_length=3, max_length=16)
    accept_offer: bool = False
    accept_personal_data: bool = False
    distribution_profile: bool = False
    distribution_map: bool = False
    distribution_purchases: bool = False
    ip: str | None = Field(default=None, max_length=64)


class GameSeenRequest(BaseModel):
    """A player got in without a fresh password check (kept session, launcher ticket)."""

    minecraft_nickname: str = Field(min_length=3, max_length=16)
    client: str = Field(default="external", pattern="^(launcher|external)$")
