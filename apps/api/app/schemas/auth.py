from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from apps.api.app.schemas.account import PlayerAccountRead, UserRead


class RegisterRequest(BaseModel):
    site_login: str = Field(min_length=3, max_length=32)
    minecraft_nickname: str = Field(min_length=3, max_length=16)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    password_repeat: str = Field(min_length=8, max_length=128)
    referral_code: str | None = Field(default=None, min_length=3, max_length=32)

    @field_validator("site_login")
    @classmethod
    def validate_site_login(cls, value: str) -> str:
        return value.strip()

    @field_validator("minecraft_nickname")
    @classmethod
    def validate_minecraft_nickname(cls, value: str) -> str:
        return value.strip()

    @field_validator("referral_code")
    @classmethod
    def validate_referral_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("password_repeat")
    @classmethod
    def validate_password_repeat(cls, value: str, info):
        password = info.data.get("password")
        if password is not None and value != password:
            raise ValueError("password_repeat must match password")
        return value


class LoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    device_name: str = Field(default="Unknown Device", min_length=2, max_length=120)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)
    device_name: str = Field(default="Unknown Device", min_length=2, max_length=120)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=16, max_length=512)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class RequestPasswordResetRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)
    new_password_repeat: str = Field(min_length=8, max_length=128)

    @field_validator("new_password_repeat")
    @classmethod
    def validate_new_password_repeat(cls, value: str, info):
        new_password = info.data.get("new_password")
        if new_password is not None and value != new_password:
            raise ValueError("new_password_repeat must match new_password")
        return value


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_in: int
    refresh_expires_in: int
    user: UserRead
    player_account: PlayerAccountRead


class RegisterResponse(BaseModel):
    message: str
    user: UserRead
    player_account: PlayerAccountRead
    verification_requested: bool = True


class LoginResponse(TokenPairResponse):
    pass


class RefreshResponse(TokenPairResponse):
    pass


class EmailActionResponse(BaseModel):
    message: str
    success: bool = True