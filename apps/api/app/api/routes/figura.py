"""Self-hosted Figura backend — HTTP API + WebSocket.

Served for ``figura.void-rp.ru`` where nginx rewrites ``/api/*`` → ``/figura/*`` and
``/ws`` → ``/figura-ws``. Protocol reverse-engineered from the Figura 1.21 client; see
``docs/figura_backend_spec.md``.
"""
from __future__ import annotations

import hashlib
import secrets
import struct
import uuid as uuidlib
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from apps.api.app.db import SessionLocal, get_db_session
from apps.api.app.models.figura import FiguraAvatar, FiguraEquipped, FiguraSession
from apps.api.app.services.figura_ws import hub
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(prefix="/figura", tags=["figura"])          # nginx maps /api/* → /figura/*
ws_router = APIRouter(tags=["figura"])                          # /figura-ws (nginx maps /ws)

MAX_AVATAR_BYTES = 512 * 1024
_AUTHID_TTL = 120


def _offline_uuid(name: str) -> str:
    """Java offline UUID: type-3 (MD5) of 'OfflinePlayer:<name>'."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(digest)))


def _session_for_token(db: Session, token: str | None) -> FiguraSession | None:
    if not token:
        return None
    return db.execute(select(FiguraSession).where(FiguraSession.token == token)).scalar_one_or_none()


def _require_session(
    db: Annotated[Session, Depends(get_db_session)],
    token: Annotated[str | None, Header(alias="token")] = None,
) -> FiguraSession:
    sess = _session_for_token(db, token)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return sess


# ── auth (offline: we trust our own launcher-gated players; no Mojang round-trip) ──
@router.get("/auth/id")
def auth_id(username: str) -> PlainTextResponse:
    server_id = secrets.token_hex(20)
    RedisCacheService().set_json(f"figura:authid:{server_id}", {"u": username}, ttl_seconds=_AUTHID_TTL)
    return PlainTextResponse(server_id)


@router.get("/auth/verify")
def auth_verify(id: str, db: Annotated[Session, Depends(get_db_session)]) -> PlainTextResponse:
    cached = RedisCacheService().get_json(f"figura:authid:{id}")
    if not cached or not cached.get("u"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expired")
    username = str(cached["u"])
    player_uuid = _offline_uuid(username)
    token = secrets.token_hex(32)
    db.add(FiguraSession(token=token, minecraft_uuid=player_uuid, minecraft_nickname=username))
    db.commit()
    RedisCacheService().delete(f"figura:authid:{id}")
    return PlainTextResponse(token)


# ── meta ──
@router.get("/")
def check_auth(session: Annotated[FiguraSession, Depends(_require_session)]) -> PlainTextResponse:
    return PlainTextResponse("ok")


@router.get("/version")
def version() -> JSONResponse:
    return JSONResponse({"release": "0.1.6", "prerelease": "0.1.6"})


@router.get("/motd")
def motd() -> PlainTextResponse:
    return PlainTextResponse('{"text":"VoidRP Figura","color":"aqua"}')


@router.get("/limits")
def limits() -> JSONResponse:
    return JSONResponse({
        "rate": {"upload": 1, "download": 50},
        "limits": {"maxAvatarSize": MAX_AVATAR_BYTES, "maxAvatars": 10, "allowedBadges": {"pride": [], "special": []}},
    })


# ── equip ──
@router.post("/equip")
async def set_equipped(
    request: Request,
    session: Annotated[FiguraSession, Depends(_require_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> PlainTextResponse:
    import json as _json
    body = _json.loads((await request.body()) or b"[]")
    equipped = [{"owner": str(e["owner"]), "id": str(e["id"])} for e in body if e.get("id")]
    row = db.execute(
        select(FiguraEquipped).where(FiguraEquipped.owner_uuid == session.minecraft_uuid)
    ).scalar_one_or_none()
    if row is None:
        row = FiguraEquipped(owner_uuid=session.minecraft_uuid, equipped=equipped, version=1)
        db.add(row)
    else:
        row.equipped = equipped
        row.version = int(row.version) + 1
    db.commit()
    await hub.notify_event(session.minecraft_uuid)
    return PlainTextResponse("ok")


# ── user info ──
@router.get("/{owner}/{avatar_id}")
def get_avatar(owner: str, avatar_id: str, db: Annotated[Session, Depends(get_db_session)]) -> Response:
    av = db.execute(
        select(FiguraAvatar).where(FiguraAvatar.owner_uuid == owner, FiguraAvatar.avatar_id == avatar_id)
    ).scalar_one_or_none()
    if av is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no avatar")
    return Response(content=av.data, media_type="application/octet-stream")


@router.put("/{avatar_id}")
async def upload_avatar(
    avatar_id: str,
    request: Request,
    session: Annotated[FiguraSession, Depends(_require_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> PlainTextResponse:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty")
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="too big")
    sha = hashlib.sha256(data).hexdigest()
    av = db.execute(
        select(FiguraAvatar).where(
            FiguraAvatar.owner_uuid == session.minecraft_uuid, FiguraAvatar.avatar_id == avatar_id
        )
    ).scalar_one_or_none()
    if av is None:
        db.add(FiguraAvatar(owner_uuid=session.minecraft_uuid, avatar_id=avatar_id,
                            data=data, sha256=sha, size_bytes=len(data)))
    else:
        av.data, av.sha256, av.size_bytes = data, sha, len(data)
    db.commit()
    await hub.notify_event(session.minecraft_uuid)
    return PlainTextResponse(sha)


@router.delete("/{avatar_id}")
def delete_avatar(
    avatar_id: str,
    session: Annotated[FiguraSession, Depends(_require_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> PlainTextResponse:
    av = db.execute(
        select(FiguraAvatar).where(
            FiguraAvatar.owner_uuid == session.minecraft_uuid, FiguraAvatar.avatar_id == avatar_id
        )
    ).scalar_one_or_none()
    if av is not None:
        db.delete(av)
        db.commit()
    return PlainTextResponse("ok")


@router.get("/{owner}")
def get_user(owner: str, db: Annotated[Session, Depends(get_db_session)]) -> JSONResponse:
    eq = db.execute(select(FiguraEquipped).where(FiguraEquipped.owner_uuid == owner)).scalar_one_or_none()
    equipped_out = []
    if eq is not None:
        for entry in (eq.equipped or []):
            av = db.execute(
                select(FiguraAvatar).where(
                    FiguraAvatar.owner_uuid == entry["owner"], FiguraAvatar.avatar_id == entry["id"]
                )
            ).scalar_one_or_none()
            if av is not None:
                equipped_out.append({"owner": entry["owner"], "id": entry["id"], "hash": av.sha256})
    return JSONResponse({
        "uuid": owner,
        "equipped": equipped_out,
        "equippedBadges": {"pride": [], "special": []},
    })


# ── WebSocket (binary; nginx maps wss://host/ws → /figura-ws) ──
@ws_router.websocket("/figura-ws")
async def figura_ws(ws: WebSocket) -> None:
    await ws.accept()
    my_uuid: str | None = None
    try:
        while True:
            msg = await ws.receive_bytes()
            if not msg:
                continue
            kind = msg[0]
            if kind == 0:  # TOKEN
                token = msg[1:].decode("utf-8", "ignore")
                db = SessionLocal()
                try:
                    sess = _session_for_token(db, token)
                finally:
                    db.close()
                if sess is None:
                    await ws.close()
                    return
                my_uuid = sess.minecraft_uuid
                await hub.register(my_uuid, ws)
                await hub.send_auth(ws)
            elif my_uuid is None:
                continue
            elif kind == 1 and len(msg) >= 6:  # PING
                ping_id = struct.unpack(">i", msg[1:5])[0]
                await hub.relay_ping(my_uuid, ping_id, msg[5], msg[6:])
            elif kind == 2 and len(msg) >= 17:  # SUB
                target = str(uuidlib.UUID(bytes=msg[1:17]))
                await hub.subscribe(my_uuid, target)
                await ws.send_bytes(bytes([2]) + msg[1:17])   # nudge: load this avatar now
            elif kind == 3 and len(msg) >= 17:  # UNSUB
                target = str(uuidlib.UUID(bytes=msg[1:17]))
                await hub.unsubscribe(my_uuid, target)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        if my_uuid is not None:
            await hub.unregister(my_uuid, ws)
