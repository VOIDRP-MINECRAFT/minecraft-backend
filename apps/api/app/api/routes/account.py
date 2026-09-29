from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.core.security import hash_opaque_token, utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.refresh_session import RefreshSession
from apps.api.app.models.user import User
from apps.api.app.schemas.account import (
    UserRead,
    AccountSecurityRead,
    AccountSkinResponse,
    MeResponse,
    PlayerSkinRead,
    RevokeOtherSessionsRequest,
    RevokeSessionsResponse,
)
from apps.api.app.services.player_skin_service import PlayerSkinService, PlayerSkinValidationError
from apps.api.app.services.redis_cache_service import RedisCacheService

router = APIRouter(tags=["account"])


def staff_user_read(session: Session, current_user: User) -> UserRead:
    """The user as the site sees it, with admin-panel access from every source (personal
    grants, roles, admin of servers). Used by /me and by login / refresh, so a fresh
    session knows at once which sections and servers the person may open."""
    from apps.api.app.core.permissions import SERVER_KEYS, access_of
    from apps.api.app.models.game_server import GameServer

    servers = session.query(GameServer.id, GameServer.slug, GameServer.is_default).all()
    access = access_of(current_user)
    # hasPermission() on the site reads `permissions` (everywhere) and `server_permissions[slug]`.
    everywhere = sorted(access.everywhere)
    per_server = {}
    admin_servers = None
    if not current_user.is_admin and access.is_staff:
        for sid, slug, _ in servers:
            extra = access.on(sid) - access.everywhere
            if extra:
                per_server[slug] = sorted(extra)
        # The admin panel's server switcher offers only servers where the person holds at
        # least one per-server permission (from any source); null = all of them.
        usable = [slug for sid, slug, _ in servers if access.on(sid) & SERVER_KEYS]
        if len(usable) < len(servers):
            admin_servers = usable
    return UserRead.model_validate(current_user).model_copy(update={
        "permissions": [] if current_user.is_admin else everywhere,
        "server_permissions": per_server,
        "administered_servers": [slug for sid, slug, _ in servers if str(sid) in access.admin_servers],
        "roles": [{"name": r.name, "color": r.color} for r in (current_user.staff_roles or [])],
        "admin_servers": admin_servers,
        "default_server": next((slug for _, slug, d in servers if d), None),
    })


def _get_player_account(*, session: Session, user_id) -> PlayerAccount:
    return session.execute(select(PlayerAccount).where(PlayerAccount.user_id == user_id)).scalar_one()


def _build_me_response(
    *,
    session: Session,
    current_user: User,
    player_account: PlayerAccount,
) -> MeResponse:
    now = utc_now()

    active_refresh_sessions = int(
        session.scalar(
            select(func.count())
            .select_from(RefreshSession)
            .where(
                RefreshSession.user_id == current_user.id,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > now,
            )
        )
        or 0
    )

    legacy_hash_present = bool(player_account.legacy_password_hash)
    legacy_ready = bool(
        player_account.legacy_auth_enabled
        and player_account.legacy_password_hash
        and player_account.legacy_hash_algo
    )

    user = staff_user_read(session, current_user)
    return MeResponse(
        user=user,
        player_account=player_account,
        security=AccountSecurityRead(
            active_refresh_sessions=active_refresh_sessions,
            must_use_launcher=bool(current_user.is_active and not player_account.legacy_auth_enabled),
            legacy_hash_present=legacy_hash_present,
            legacy_ready=legacy_ready,
        ),
    )


def get_player_skin_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> PlayerSkinService:
    return PlayerSkinService(session=session)


@router.get("/me", response_model=MeResponse)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MeResponse:
    player_account = _get_player_account(session=session, user_id=current_user.id)
    return _build_me_response(
        session=session,
        current_user=current_user,
        player_account=player_account,
    )


@router.post("/account/revoke-other-sessions", response_model=RevokeSessionsResponse)
def revoke_other_sessions(
    payload: RevokeOtherSessionsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> RevokeSessionsResponse:
    current_refresh_token_hash = hash_opaque_token(payload.refresh_token)
    now = utc_now()

    refresh_sessions = session.execute(
        select(RefreshSession).where(
            RefreshSession.user_id == current_user.id,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
            RefreshSession.token_hash != current_refresh_token_hash,
        )
    ).scalars().all()

    revoked_sessions = 0
    for refresh_session in refresh_sessions:
        refresh_session.revoked_at = now
        refresh_session.last_used_at = now
        revoked_sessions += 1

    session.commit()

    return RevokeSessionsResponse(
        message="Другие активные сессии завершены.",
        revoked_sessions=revoked_sessions,
    )


@router.get("/account/skin", response_model=PlayerSkinRead)
def get_my_skin(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayerSkinService, Depends(get_player_skin_service)],
) -> PlayerSkinRead:
    return service.to_read(service.get_for_user(current_user))


@router.post("/account/skin", response_model=AccountSkinResponse)
async def upload_my_skin(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayerSkinService, Depends(get_player_skin_service)],
    file: UploadFile = File(...),
    model_variant: str = Form(default="classic"),
) -> AccountSkinResponse:
    try:
        skin = await service.save_for_user(
            current_user=current_user,
            upload=file,
            model_variant=model_variant,
        )
    except PlayerSkinValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    cache = RedisCacheService()
    cache.delete(f"player_access:{(current_user.player_account.minecraft_nickname_normalized if current_user.player_account else '').strip()}")
    cache.delete(f"launcher_dashboard:user:{current_user.id}")
    if current_user.player_account is not None:
        cache.delete(f"player_skin:{current_user.player_account.minecraft_nickname_normalized}")
    return AccountSkinResponse(
        message="Скин успешно сохранён.",
        skin=service.to_read(skin),
    )


@router.delete("/account/skin", response_model=AccountSkinResponse)
def delete_my_skin(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PlayerSkinService, Depends(get_player_skin_service)],
) -> AccountSkinResponse:
    service.delete_for_user(current_user=current_user)
    cache = RedisCacheService()
    cache.delete(f"launcher_dashboard:user:{current_user.id}")
    if current_user.player_account is not None:
        cache.delete(f"player_skin:{current_user.player_account.minecraft_nickname_normalized}")
    return AccountSkinResponse(
        message="Скин удалён.",
        skin=service.to_read(None),
    )
