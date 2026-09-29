"""Account security: 2FA (required for the admin panel), password re-confirmation before
dangerous actions, and «Активные входы» — signed-in devices, like in Telegram."""
from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import mfa
from apps.api.app.core.audit import client_ip, record_audit
from apps.api.app.core.devices import describe
from apps.api.app.core.security import utc_now, verify_password
from apps.api.app.core.sign_ins import revoke_devices
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_device, get_current_user
from apps.api.app.models.auth_device import AuthDevice
from apps.api.app.models.user import User

router = APIRouter(prefix="/auth", tags=["security"])

_User = Annotated[User, Depends(get_current_user)]
_Device = Annotated[AuthDevice, Depends(get_current_device)]
_Db = Annotated[Session, Depends(get_db_session)]


def is_staff(user: User) -> bool:
    return bool(user.is_admin or user.is_moderator or user.admin_server_ids)


def mfa_fresh(device: AuthDevice | None) -> bool:
    return device is not None and device.mfa_at is not None and utc_now() - device.mfa_at < mfa.MFA_TTL


def reauth_fresh(device: AuthDevice | None) -> bool:
    return device is not None and device.reauth_at is not None and utc_now() - device.reauth_at < mfa.REAUTH_TTL


def _telegram_send(chat_id: int, text: str) -> bool:
    from apps.api.app.services.news_service import _http_post_json

    token = get_settings().telegram_bot_token
    return bool(token) and _http_post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                                            {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def _status(user: User, device: AuthDevice | None) -> dict:
    return {
        "enabled": user.mfa_enabled,
        "required": is_staff(user),
        # The admin panel really asks for it (STAFF_MFA_REQUIRED emergency switch).
        "enforced": is_staff(user) and bool(getattr(get_settings(), "staff_mfa_required", True)),
        "totp": bool(user.mfa_totp_enabled_at),
        "telegram": bool(user.mfa_telegram_enabled_at and user.telegram_user_id),
        "telegram_linked": bool(user.telegram_user_id),
        "backup_left": len(user.mfa_backup_hashes or []),
        "device_verified": mfa_fresh(device),
        "verified_until": (device.mfa_at + mfa.MFA_TTL).isoformat() if mfa_fresh(device) else None,
    }


def _mark_verified(session: Session, user: User, device: AuthDevice, method: str, request: Request | None) -> None:
    device.mfa_at = utc_now()
    device.mfa_failures = 0
    device.mfa_code_hash = None
    session.commit()
    if is_staff(user) and user.telegram_user_id:
        d = describe(device.user_agent, device.device_name)
        place = device.last_location or device.location or "место неизвестно"
        _telegram_send(user.telegram_user_id,
                       f"🔐 <b>Вход в админку VoidRP</b>\n{d['title']}\n{place} · IP {device.last_ip or device.ip or '—'}\n\n"
                       "Если это не ты — открой «Активные входы» на сайте и заверши этот вход, затем смени пароль.")
    record_audit(session, actor=user, category="security", action="mfa_passed", target_type="device",
                 target_id=str(device.id), meta={"method": method}, request=request)


def _fail(session: Session, device: AuthDevice, what: str = "код") -> None:
    device.mfa_failures = (device.mfa_failures or 0) + 1
    if device.mfa_failures >= mfa.MAX_FAILURES:
        revoke_devices(session, device.user_id, only=device.id)
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Слишком много неверных попыток — вход на этом устройстве завершён. Войди заново.")
    session.commit()
    left = mfa.MAX_FAILURES - device.mfa_failures
    word = "Неверный пароль" if what == "пароль" else "Неверный код"
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{word}. Осталось попыток: {left}")


# ── 2FA ──────────────────────────────────────────────────────────────────────

class CodeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=20)


class PasswordBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


@router.get("/mfa")
def mfa_status(user: _User, session: _Db, request: Request) -> dict:
    from apps.api.app.dependencies.auth import device_from_token

    token = (request.headers.get("authorization") or "")[7:]
    return _status(user, device_from_token(token, session))


@router.post("/mfa/totp/start")
def totp_start(user: _User, device: _Device, session: _Db) -> dict:
    """A new secret for an authenticator app (shown as a QR code and as text). It starts
    working only after /mfa/totp/confirm with a code from the app."""
    if user.mfa_totp_enabled_at and not reauth_fresh(device):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reauth_required")
    secret = mfa.new_totp_secret()
    user.mfa_totp_secret = mfa.encrypt(secret)
    user.mfa_totp_enabled_at = None
    session.commit()
    return {"secret": secret, "uri": mfa.otpauth_uri(secret, user.site_login)}


@router.post("/mfa/totp/confirm")
def totp_confirm(body: CodeBody, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    secret = mfa.decrypt(user.mfa_totp_secret)
    if not secret:
        raise HTTPException(status_code=400, detail="Сначала отсканируй QR-код в приложении")
    step = mfa.verify_totp(secret, body.code)
    if step is None:
        raise HTTPException(status_code=400, detail="Код не подошёл — проверь время на телефоне и введи свежий код")
    user.mfa_totp_enabled_at = utc_now()
    user.mfa_totp_last_step = step
    codes = None
    if not user.mfa_backup_hashes:
        codes, user.mfa_backup_hashes = mfa.new_backup_codes()
    record_audit(session, actor=user, category="security", action="mfa_enable", meta={"method": "totp"}, request=request)
    _mark_verified(session, user, device, "totp", None)
    return {**_status(user, device), "backup_codes": codes}


@router.post("/mfa/telegram/send")
def telegram_send(user: _User, device: _Device, session: _Db) -> dict:
    """Sends a 6-digit code to the linked Telegram (to switch the method on, or to pass 2FA)."""
    if not user.telegram_user_id:
        raise HTTPException(status_code=400, detail="Сначала привяжи Telegram к аккаунту в профиле")
    if device.mfa_code_expires_at and device.mfa_code_expires_at - mfa.TELEGRAM_CODE_TTL + timedelta(seconds=45) > utc_now():
        raise HTTPException(status_code=429, detail="Код уже отправлен — новый можно запросить через минуту")
    code, code_hash = mfa.new_numeric_code()
    d = describe(device.user_agent, device.device_name)
    if not _telegram_send(user.telegram_user_id,
                          f"🔐 Код для входа в админку VoidRP: <code>{code}</code>\n{d['title']} · "
                          f"{device.last_location or device.location or 'место неизвестно'}\n"
                          "Действует 5 минут. Никому его не сообщай."):
        raise HTTPException(status_code=502, detail="Telegram не принял сообщение — попробуй ещё раз или войди кодом из приложения")
    device.mfa_code_hash = code_hash
    device.mfa_code_expires_at = utc_now() + mfa.TELEGRAM_CODE_TTL
    session.commit()
    return {"sent": True}


@router.post("/mfa/telegram/confirm")
def telegram_confirm(body: CodeBody, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    if not _telegram_code_ok(device, body.code):
        _fail(session, device)
    user.mfa_telegram_enabled_at = utc_now()
    codes = None
    if not user.mfa_backup_hashes:
        codes, user.mfa_backup_hashes = mfa.new_backup_codes()
    record_audit(session, actor=user, category="security", action="mfa_enable", meta={"method": "telegram"}, request=request)
    _mark_verified(session, user, device, "telegram", None)
    return {**_status(user, device), "backup_codes": codes}


def _telegram_code_ok(device: AuthDevice, code: str) -> bool:
    return bool(device.mfa_code_expires_at and device.mfa_code_expires_at > utc_now()
                and mfa.check_numeric_code(device.mfa_code_hash, code))


@router.post("/mfa/verify")
def mfa_verify(body: CodeBody, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    """Unlocks the admin panel on this device for 12 hours: a code from the app, from
    Telegram, or a backup code (used up)."""
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="mfa_setup_required")
    method = None
    secret = mfa.decrypt(user.mfa_totp_secret) if user.mfa_totp_enabled_at else None
    if secret and (step := mfa.verify_totp(secret, body.code, user.mfa_totp_last_step)) is not None:
        user.mfa_totp_last_step, method = step, "totp"
    elif user.mfa_telegram_enabled_at and _telegram_code_ok(device, body.code):
        method = "telegram"
    elif (rest := mfa.use_backup_code(user.mfa_backup_hashes or [], body.code)) is not None:
        user.mfa_backup_hashes, method = rest, "backup"
    if method is None:
        _fail(session, device)
    _mark_verified(session, user, device, method, request)
    return _status(user, device)


@router.post("/mfa/backup-codes")
def new_backup_codes(user: _User, device: _Device, session: _Db, request: Request) -> dict:
    """New backup codes (the old ones stop working). Needs the password re-entered."""
    if not reauth_fresh(device):
        raise HTTPException(status_code=403, detail="reauth_required")
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="Сначала подключи 2FA")
    codes, user.mfa_backup_hashes = mfa.new_backup_codes()
    record_audit(session, actor=user, category="security", action="mfa_backup_codes", request=request)
    session.commit()
    return {"backup_codes": codes}


class DisableBody(BaseModel):
    method: str = Field(..., pattern="^(totp|telegram)$")


@router.post("/mfa/disable")
def mfa_disable(body: DisableBody, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    """Switches a method off (password re-entered first). Staff keep at least one — 2FA is
    required for the admin panel."""
    if not reauth_fresh(device):
        raise HTTPException(status_code=403, detail="reauth_required")
    others = bool(user.mfa_telegram_enabled_at and user.telegram_user_id) if body.method == "totp" else bool(user.mfa_totp_enabled_at)
    if is_staff(user) and not others:
        raise HTTPException(status_code=400, detail="Для работы в админке нужен хотя бы один способ 2FA — сначала подключи другой")
    if body.method == "totp":
        user.mfa_totp_secret = None
        user.mfa_totp_enabled_at = None
        user.mfa_totp_last_step = None
    else:
        user.mfa_telegram_enabled_at = None
    if not user.mfa_enabled:
        user.mfa_backup_hashes = []
    record_audit(session, actor=user, category="security", action="mfa_disable", meta={"method": body.method}, request=request)
    session.commit()
    return _status(user, device)


# ── password re-confirmation ─────────────────────────────────────────────────

@router.post("/reauth")
def reauth(body: PasswordBody, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    if not verify_password(body.password, user.password_hash):
        _fail(session, device, "пароль")
    device.reauth_at = utc_now()
    device.mfa_failures = 0
    session.commit()
    record_audit(session, actor=user, category="security", action="reauth", request=request)
    return {"ok": True, "until": (device.reauth_at + mfa.REAUTH_TTL).isoformat()}


# ── «Активные входы» ─────────────────────────────────────────────────────────

def device_view(d: AuthDevice, current_id: UUID | None) -> dict:
    info = describe(d.user_agent, d.device_name)
    return {
        "id": str(d.id), **info,
        "ip": d.last_ip or d.ip, "location": d.last_location or d.location,
        "first_ip": d.ip, "first_location": d.location,
        "created_at": d.created_at.isoformat(), "last_seen_at": d.last_seen_at.isoformat(),
        "current": d.id == current_id, "mfa": mfa_fresh(d),
    }


def active_devices(session: Session, user_id: UUID) -> list[AuthDevice]:
    return session.scalars(select(AuthDevice).where(
        AuthDevice.user_id == user_id, AuthDevice.revoked_at.is_(None), AuthDevice.expires_at > utc_now(),
    ).order_by(AuthDevice.last_seen_at.desc())).all()


@router.get("/devices")
def list_devices(user: _User, device: _Device, session: _Db) -> dict:
    return {"items": [device_view(d, device.id) for d in active_devices(session, user.id)]}


@router.delete("/devices/{device_id}")
def end_device(device_id: UUID, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    if device_id == device.id:
        raise HTTPException(status_code=400, detail="Это устройство — чтобы выйти с него, нажми «Выйти»")
    n = revoke_devices(session, user.id, only=device_id)
    session.commit()
    if n:
        record_audit(session, actor=user, category="security", action="device_end", target_type="device",
                     target_id=str(device_id), request=request)
    return {"ended": n}


@router.post("/devices/end-others")
def end_other_devices(user: _User, device: _Device, session: _Db, request: Request) -> dict:
    n = revoke_devices(session, user.id, keep=device.id)
    session.commit()
    record_audit(session, actor=user, category="security", action="devices_end_others", meta={"count": n}, request=request)
    return {"ended": n}
