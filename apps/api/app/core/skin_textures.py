"""Signed skin textures for offline-mode game servers.

A client shows a skin from the server's game profile only when its ``textures`` property
carries Mojang's signature. A VoidRP skin is an arbitrary PNG, so it is signed through
MineSkin (which uploads it to a Mojang account and hands back the signed property) once
per picture and model, and kept in ``skin_textures``. A player without a VoidRP skin gets
the Mojang skin of their nickname, as SkinsRestorer did.

Nothing here blocks a request: a missing signature is queued for a background worker and
the caller answers without it; the game server asks again a little later.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models.skin_texture import SkinTexture
from apps.api.app.services.redis_cache_service import RedisCacheService

log = logging.getLogger(__name__)

MINESKIN_URL = "https://api.mineskin.org/v2/generate"
USER_AGENT = "VoidRP/1.0 (+https://void-rp.ru)"
MOJANG_TTL = 6 * 3600          # a nickname's Mojang skin rarely changes
MOJANG_MISS_TTL = 3600         # not a Mojang name, or Mojang was down

# One MineSkin worker: without a key it allows a request every ~6 s, so queued skins go
# through one at a time. Mojang lookups are quick and have their own pool.
_sign_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skin-sign")
_mojang_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="skin-mojang")
_pending: set[str] = set()
_pending_lock = threading.Lock()
_next_request_at = 0.0


def _variant(value: str | None) -> str:
    return "slim" if (value or "").strip().lower() == "slim" else "classic"


def lookup(session: Session, sha256: str, model_variant: str | None) -> SkinTexture | None:
    return session.scalar(
        select(SkinTexture).where(
            SkinTexture.sha256 == sha256, SkinTexture.model_variant == _variant(model_variant)
        )
    )


def _claim(key: str) -> bool:
    with _pending_lock:
        if key in _pending:
            return False
        _pending.add(key)
        return True


def _release(key: str) -> None:
    with _pending_lock:
        _pending.discard(key)


def _forget_player_cache(nick_normalized: str | None) -> None:
    if nick_normalized:
        RedisCacheService().delete(f"player_skin:{nick_normalized}")


# ── VoidRP skins → MineSkin ──────────────────────────────────────────────────
def request_signing(sha256: str, model_variant: str | None, url: str,
                    nick_normalized: str | None = None) -> None:
    """Queue a skin for signing unless it is signed or already queued."""
    key = f"sign:{sha256}:{_variant(model_variant)}"
    if not _claim(key):
        return

    def job() -> None:
        try:
            sign_now(sha256, model_variant, url)
            _forget_player_cache(nick_normalized)
        except Exception:  # noqa: BLE001 — a failed signing is retried on the next request
            log.exception("Could not sign skin %s", sha256[:12])
        finally:
            _release(key)

    _sign_pool.submit(job)


def sign_now(sha256: str, model_variant: str | None, url: str) -> SkinTexture | None:
    """Sign one skin through MineSkin and store it. Blocking; respects the rate limit."""
    from apps.api.app.db import SessionLocal  # local: keeps this module import-light

    variant = _variant(model_variant)
    with SessionLocal() as session:
        existing = lookup(session, sha256, variant)
        if existing is not None:
            return existing

    data = _mineskin_generate(url, variant, name=f"voidrp-{sha256[:10]}")
    if data is None:
        return None

    with SessionLocal() as session:
        row = SkinTexture(sha256=sha256, model_variant=variant, value=data["value"],
                          signature=data["signature"], mineskin_uuid=data.get("uuid"))
        session.add(row)
        try:
            session.commit()
        except IntegrityError:  # signed meanwhile by another process
            session.rollback()
            return lookup(session, sha256, variant)
        session.refresh(row)
        log.info("Signed skin %s (%s) via MineSkin", sha256[:12], variant)
        return row


def _mineskin_generate(url: str, variant: str, name: str) -> dict | None:
    global _next_request_at
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    key = (get_settings().mineskin_api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"url": url, "variant": variant, "visibility": "unlisted", "name": name}

    for _attempt in range(4):
        wait = _next_request_at - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            resp = httpx.post(MINESKIN_URL, json=body, headers=headers, timeout=60.0)
        except httpx.HTTPError as exc:
            log.warning("MineSkin unreachable: %s", exc)
            _next_request_at = time.time() + 10
            continue
        payload = _json(resp)
        delay = _delay_seconds(payload)
        _next_request_at = time.time() + max(delay, 1.0)
        if resp.status_code == 429:
            continue
        if resp.status_code >= 400 or not payload.get("success"):
            log.warning("MineSkin refused %s: http %s %s", url, resp.status_code,
                        str(payload.get("errors") or payload.get("error") or "")[:300] if payload else resp.text[:300])
            return None
        texture = ((payload.get("skin") or {}).get("texture") or {}).get("data") or {}
        if not texture.get("value") or not texture.get("signature"):
            log.warning("MineSkin answer without a signed texture for %s", url)
            return None
        return {"value": texture["value"], "signature": texture["signature"],
                "uuid": (payload.get("skin") or {}).get("uuid")}
    return None


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _delay_seconds(payload: dict) -> float:
    try:
        rate = payload.get("rateLimit") or {}
        nxt = (rate.get("next") or {}).get("relative")
        if nxt is not None:
            return max(float(nxt) / 1000.0, float((rate.get("delay") or {}).get("seconds") or 0))
        return float((rate.get("delay") or {}).get("seconds") or 6)
    except (TypeError, ValueError):
        return 6.0


# ── No VoidRP skin → the Mojang skin of the nickname ─────────────────────────
def mojang_textures(nickname: str, nick_normalized: str) -> dict | None:
    """Cached signed Mojang texture of a nickname, or None (lookup queued if unknown)."""
    cached = RedisCacheService().get_json(f"mojang_skin:{nick_normalized}")
    if cached is not None:
        return cached if cached.get("value") else None

    key = f"mojang:{nick_normalized}"
    if _claim(key):
        def job() -> None:
            try:
                found = _fetch_mojang(nickname)
                RedisCacheService().set_json(
                    f"mojang_skin:{nick_normalized}", found or {"value": None},
                    ttl_seconds=MOJANG_TTL if found else MOJANG_MISS_TTL,
                )
                if found:
                    _forget_player_cache(nick_normalized)
            except Exception:  # noqa: BLE001
                log.exception("Mojang skin lookup failed for %s", nickname)
            finally:
                _release(key)

        _mojang_pool.submit(job)
    return None


def _fetch_mojang(nickname: str) -> dict | None:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=8.0, headers=headers) as http:
        r = http.get(f"https://api.mojang.com/users/profiles/minecraft/{nickname}")
        if r.status_code != 200:
            return None
        uuid = (_json(r) or {}).get("id")
        if not uuid:
            return None
        r = http.get(f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid}",
                     params={"unsigned": "false"})
        if r.status_code != 200:
            return None
        for prop in (_json(r).get("properties") or []):
            if prop.get("name") == "textures" and prop.get("value") and prop.get("signature"):
                return {"value": prop["value"], "signature": prop["signature"]}
    return None
