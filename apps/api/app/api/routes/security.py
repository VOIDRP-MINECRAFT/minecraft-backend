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
        "passkey": bool(user.mfa_passkeys),
        "passkeys": [{"id": str(k.id), "name": k.name, "synced": k.synced, "created_at": k.created_at.isoformat(),
                      "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None} for k in user.mfa_passkeys],
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
    word = {"пароль": "Неверный пароль", "ключ": "Ключ не подошёл"}.get(what, "Неверный код")
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
    others = (bool(user.mfa_telegram_enabled_at and user.telegram_user_id) if body.method == "totp"
              else bool(user.mfa_totp_enabled_at)) or bool(user.mfa_passkeys)
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


# ── passkeys (WebAuthn) ──────────────────────────────────────────────────────

import json as _json  # noqa: E402

import webauthn  # noqa: E402
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url  # noqa: E402
from webauthn.helpers.structs import (  # noqa: E402
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from apps.api.app.models.mfa_passkey import MfaPasskey  # noqa: E402

_CHALLENGE_TTL = timedelta(minutes=5)


def _rp() -> tuple[str, list[str]]:
    from urllib.parse import urlparse

    s = get_settings()
    base = s.website_base_url.rstrip("/")
    rp_id = s.webauthn_rp_id or urlparse(base).hostname or "void-rp.ru"
    origins = [base] + [o.strip().rstrip("/") for o in (s.webauthn_extra_origins or "").split(",") if o.strip()]
    return rp_id, origins


def _take_challenge(device: AuthDevice) -> bytes:
    raw = device.webauthn_challenge
    ok = raw and device.webauthn_challenge_expires_at and device.webauthn_challenge_expires_at > utc_now()
    device.webauthn_challenge = None
    device.webauthn_challenge_expires_at = None
    if not ok:
        raise HTTPException(status_code=400, detail="Запрос устарел — нажми ещё раз")
    return base64url_to_bytes(raw)


def _passkey_name(device: AuthDevice, attachment: str | None, synced: bool) -> str:
    if attachment == "cross-platform":
        return "Ключ безопасности"
    os_name = (describe(device.user_agent, device.device_name).get("os") or "")
    if os_name.startswith("Windows"):
        return "Windows Hello"
    if os_name.startswith(("iOS", "macOS")):
        return "Face ID / Touch ID"
    if os_name.startswith("Android"):
        return "Android"
    return "Ключ доступа" + (" (синхронизируется)" if synced else "")


class PasskeyBody(BaseModel):
    credential: dict
    name: str | None = Field(default=None, max_length=80)


@router.post("/mfa/passkey/register/options")
def passkey_register_options(user: _User, device: _Device, session: _Db) -> dict:
    """Options for navigator.credentials.create(): a new passkey for this account."""
    if user.mfa_enabled and not (mfa_fresh(device) or reauth_fresh(device)):
        # Adding a key to an account that already has 2FA — prove it is you first.
        raise HTTPException(status_code=403, detail="reauth_required")
    rp_id, _ = _rp()
    options = webauthn.generate_registration_options(
        rp_id=rp_id, rp_name="VoidRP", user_id=user.id.bytes, user_name=user.site_login,
        user_display_name=user.site_login,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(k.credential_id)) for k in user.mfa_passkeys],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.PREFERRED),
    )
    device.webauthn_challenge = bytes_to_base64url(options.challenge)
    device.webauthn_challenge_expires_at = utc_now() + _CHALLENGE_TTL
    session.commit()
    return _json.loads(webauthn.options_to_json(options))


@router.post("/mfa/passkey/register/verify")
def passkey_register_verify(body: PasskeyBody, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    challenge = _take_challenge(device)
    rp_id, origins = _rp()
    try:
        v = webauthn.verify_registration_response(credential=body.credential, expected_challenge=challenge,
                                                  expected_rp_id=rp_id, expected_origin=origins)
    except Exception as exc:  # noqa: BLE001 — the library raises several kinds
        session.commit()
        raise HTTPException(status_code=400, detail=f"Ключ не принят: {exc}")
    synced = bool(getattr(v, "credential_backed_up", False))
    attachment = body.credential.get("authenticatorAttachment")
    key = MfaPasskey(
        user_id=user.id, credential_id=bytes_to_base64url(v.credential_id), public_key=v.credential_public_key,
        sign_count=v.sign_count, transports=list((body.credential.get("response") or {}).get("transports") or []),
        name=(body.name or "").strip()[:80] or _passkey_name(device, attachment, synced), synced=synced,
        last_used_at=utc_now(),
    )
    session.add(key)
    codes = None
    if not user.mfa_backup_hashes:
        codes, user.mfa_backup_hashes = mfa.new_backup_codes()
    session.flush()
    session.refresh(user)
    record_audit(session, actor=user, category="security", action="mfa_enable",
                 meta={"method": "passkey", "name": key.name}, request=request)
    _mark_verified(session, user, device, "passkey", None)
    return {**_status(user, device), "backup_codes": codes}


@router.post("/mfa/passkey/auth/options")
def passkey_auth_options(user: _User, device: _Device, session: _Db) -> dict:
    """Options for navigator.credentials.get(): unlock the admin panel with a passkey."""
    if not user.mfa_passkeys:
        raise HTTPException(status_code=400, detail="Ключей доступа нет — войди кодом")
    rp_id, _ = _rp()
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(k.credential_id)) for k in user.mfa_passkeys],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    device.webauthn_challenge = bytes_to_base64url(options.challenge)
    device.webauthn_challenge_expires_at = utc_now() + _CHALLENGE_TTL
    session.commit()
    return _json.loads(webauthn.options_to_json(options))


@router.post("/mfa/passkey/auth/verify")
def passkey_auth_verify(body: PasskeyBody, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    challenge = _take_challenge(device)
    raw_id = str(body.credential.get("id") or body.credential.get("rawId") or "")
    key = next((k for k in user.mfa_passkeys if k.credential_id == raw_id), None)
    if key is None:
        _fail(session, device, "ключ")
    rp_id, origins = _rp()
    try:
        v = webauthn.verify_authentication_response(
            credential=body.credential, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origins,
            credential_public_key=key.public_key, credential_current_sign_count=key.sign_count)
    except Exception:  # noqa: BLE001
        _fail(session, device, "ключ")
    key.sign_count = v.new_sign_count
    key.last_used_at = utc_now()
    _mark_verified(session, user, device, "passkey", request)
    return _status(user, device)


@router.delete("/mfa/passkeys/{key_id}")
def passkey_delete(key_id: UUID, user: _User, device: _Device, session: _Db, request: Request) -> dict:
    if not reauth_fresh(device):
        raise HTTPException(status_code=403, detail="reauth_required")
    key = next((k for k in user.mfa_passkeys if k.id == key_id), None)
    if key is None:
        raise HTTPException(status_code=404, detail="Ключ не найден")
    others = bool(user.mfa_totp_enabled_at or (user.mfa_telegram_enabled_at and user.telegram_user_id)
                  or len(user.mfa_passkeys) > 1)
    if is_staff(user) and not others:
        raise HTTPException(status_code=400, detail="Для работы в админке нужен хотя бы один способ 2FA — сначала подключи другой")
    user.mfa_passkeys.remove(key)
    session.flush()
    if not user.mfa_enabled:
        user.mfa_backup_hashes = []
    record_audit(session, actor=user, category="security", action="mfa_disable",
                 meta={"method": "passkey", "name": key.name}, request=request)
    session.commit()
    return _status(user, device)
