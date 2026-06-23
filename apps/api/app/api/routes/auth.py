from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.schemas.auth import (
    EmailActionResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    RequestPasswordResetRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from apps.api.app.services.auth_service import (
    AuthService,
    AuthenticationError,
    ConflictError,
    TokenValidationError,
)
from apps.api.app.services.email_service import LoggingEmailService, ResendEmailService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_email_service():
    settings = get_settings()
    if settings.email_backend == "resend":
        return ResendEmailService(settings=settings)
    return LoggingEmailService()


def get_auth_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthService:
    return AuthService(session=session, email_service=get_email_service())


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> RegisterResponse:
    try:
        user, player_account = auth_service.register_user(
            site_login=payload.site_login,
            minecraft_nickname=payload.minecraft_nickname,
            email=payload.email,
            password=payload.password,
            referral_code=payload.referral_code,
        )
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=translate_user_message(str(exc)),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=translate_user_message(str(exc)),
        ) from exc

    return RegisterResponse(
        message="Аккаунт создан. Мы отправили письмо для подтверждения почты.",
        user=user,
        player_account=player_account,
        verification_requested=True,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    try:
        result = auth_service.login(
            login=payload.login,
            password=payload.password,
            device_name=payload.device_name,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate_user_message(str(exc)),
        ) from exc

    return LoginResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        access_expires_in=result.access_expires_in,
        refresh_expires_in=result.refresh_expires_in,
        user=result.user,
        player_account=result.player_account,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    payload: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> RefreshResponse:
    try:
        result = auth_service.refresh(
            raw_refresh_token=payload.refresh_token,
            device_name=payload.device_name,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate_user_message(str(exc)),
        ) from exc

    return RefreshResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        access_expires_in=result.access_expires_in,
        refresh_expires_in=result.refresh_expires_in,
        user=result.user,
        player_account=result.player_account,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: LogoutRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    auth_service.logout(raw_refresh_token=payload.refresh_token)


@router.post("/verify-email", response_model=EmailActionResponse)
def verify_email(
    payload: VerifyEmailRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> EmailActionResponse:
    try:
        auth_service.verify_email(raw_token=payload.token)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translate_user_message(str(exc)),
        ) from exc

    return EmailActionResponse(message="Почта успешно подтверждена.")



def _render_email_confirmation_page(
    *,
    success: bool,
    title: str,
    message: str,
    website_url: str,
) -> HTMLResponse:
    safe_title = escape(title)
    safe_message = escape(message)
    safe_website_url = escape(website_url)

    banner_color = "#16a34a" if success else "#dc2626"
    banner_title = "Успешно" if success else "Ошибка"

    html = f"""<!DOCTYPE html>
<html lang=\"ru\">
  <head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>{safe_title}</title>
  </head>
  <body style=\"margin:0;padding:0;background:#0f1115;font-family:Arial,Helvetica,sans-serif;color:#e8ecf1;\">
    <div style=\"max-width:720px;margin:0 auto;padding:32px 16px;\">
      <div style=\"background:#171b22;border:1px solid #2b3442;border-radius:20px;overflow:hidden;\">
        <div style=\"padding:16px 24px;background:{banner_color};font-size:14px;font-weight:700;\">
          {banner_title}
        </div>
        <div style=\"padding:32px;\">
          <div style=\"font-size:28px;font-weight:700;line-height:1.2;margin-bottom:12px;color:#ffffff;\">
            {safe_title}
          </div>
          <div style=\"font-size:16px;line-height:1.7;color:#c7d0db;margin-bottom:24px;\">
            {safe_message}
          </div>
          <a href=\"{safe_website_url}\" style=\"display:inline-block;padding:14px 22px;border-radius:12px;background:#5865f2;color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;\">
            Перейти на сайт
          </a>
        </div>
      </div>
    </div>
  </body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/verify-email/confirm", response_class=HTMLResponse)
def verify_email_confirm(
    token: str = Query(min_length=16, max_length=512),
    auth_service: Annotated[AuthService, Depends(get_auth_service)] = None,
):
    settings = get_settings()

    try:
        auth_service.verify_email(raw_token=token)
    except TokenValidationError as exc:
        return _render_email_confirmation_page(
            success=False,
            title="Подтверждение не выполнено",
            message=f"Не удалось подтвердить почту: {translate_user_message(str(exc))}",
            website_url=settings.website_base_url,
        )

    return _render_email_confirmation_page(
        success=True,
        title="Почта подтверждена",
        message="Адрес электронной почты успешно подтверждён. Теперь можно вернуться на сайт VoidRP.",
        website_url=settings.website_base_url,
    )


@router.post("/resend-verification", response_model=EmailActionResponse)
def resend_verification(
    payload: ResendVerificationRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> EmailActionResponse:
    auth_service.resend_verification_email(email=payload.email)
    return EmailActionResponse(
        message="Если аккаунт существует и почта ещё не подтверждена, мы отправили новое письмо для подтверждения."
    )


@router.post("/request-password-reset", response_model=EmailActionResponse)
def request_password_reset(
    payload: RequestPasswordResetRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> EmailActionResponse:
    auth_service.request_password_reset(email=payload.email)
    return EmailActionResponse(
        message="Если аккаунт существует, мы отправили письмо для сброса пароля."
    )


@router.post("/reset-password", response_model=EmailActionResponse)
def reset_password(
    payload: ResetPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> EmailActionResponse:
    try:
        auth_service.reset_password(raw_token=payload.token, new_password=payload.new_password)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translate_user_message(str(exc)),
        ) from exc

    return EmailActionResponse(message="Пароль успешно изменён.")
