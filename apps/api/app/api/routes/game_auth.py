"""Account login and registration driven from inside the game.

The plugin servers (Origins and anything else without our own launcher mod) show
the player a native Minecraft dialog and post what they typed here, so a player
who arrives from a third-party client ends up with the very same VoidRP account
they would have created on the site — one account, one password, consents
recorded the same way. Everything the site's ``/auth/register`` does is reused;
only the entry point differs, and consents are stamped ``source="game"``.
"""

from __future__ import annotations

import ipaddress
from datetime import timedelta

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.core.legal_documents import DOC_DISTRIBUTION, DOC_OFFER, DOC_PERSONAL_DATA
from apps.api.app.core.security import verify_password
from apps.api.app.core.user_messages import translate_user_message
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret, require_game_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_activity import CLIENT_EXTERNAL, CLIENT_LAUNCHER
from apps.api.app.services.player_activity_service import PlayerActivityService
from apps.api.app.core.security import utc_now
from apps.api.app.models.play_ticket import PlayTicket
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.game_auth import (
    GameAccountStateResponse,
    GameConsentRequest,
    GameLoginRequest,
    GameLoginResponse,
    GameRegisterRequest,
    GameLauncherTicketRequest,
    GameSeenRequest,
)
from apps.api.app.services.auth_service import AuthService, ConflictError
from apps.api.app.services.consent_service import ConsentService
from apps.api.app.services.email_service import LoggingEmailService, ResendEmailService
from apps.api.app.config import get_settings
from apps.api.app.services.redis_cache_service import RedisCacheService
from apps.api.app.utils.normalization import normalize_minecraft_nickname

router = APIRouter(
    prefix="/server/auth/game",
    tags=["server-auth"],
    dependencies=[Depends(require_game_auth_secret)],
)

# A wrong password is cheap to retry over a socket, so the same nickname is locked
# out for a while after a handful of misses. Deliberately per nickname rather than
# per IP: the attacker picks the IP, the victim's nickname is what we protect.
MAX_FAILED_ATTEMPTS = 6
LOCKOUT_SECONDS = 600


# How recently the launcher must have taken the ticket for this path to accept it.
LAUNCHER_TICKET_WINDOW_MINUTES = 10


def _is_private(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_private or ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def _same_origin(issued_ip: str, joining_ip: str) -> bool:
    if issued_ip == joining_ip:
        return True
    # A LAN player: both sides are local, so the pair cannot come from the internet.
    return _is_private(issued_ip) and _is_private(joining_ip)


def _auth_service(session: Session) -> AuthService:
    settings = get_settings()
    email_service = ResendEmailService(settings=settings) if settings.email_backend == "resend" else LoggingEmailService()
    return AuthService(session=session, email_service=email_service)


def _find_account(session: Session, nickname: str) -> PlayerAccount | None:
    _, normalized = normalize_minecraft_nickname(nickname)
    return (
        session.execute(
            select(PlayerAccount)
            .options(joinedload(PlayerAccount.user))
            .where(PlayerAccount.minecraft_nickname_normalized == normalized)
        )
        .unique()
        .scalar_one_or_none()
    )


def _attempts_key(nickname: str) -> str:
    _, normalized = normalize_minecraft_nickname(nickname)
    return f"game_auth_fail:{normalized}"


def _register_failure(cache: RedisCacheService, nickname: str) -> None:
    key = _attempts_key(nickname)
    current = cache.get_json(key)
    count = int(current) + 1 if isinstance(current, int) else 1
    cache.set_json(key, count, ttl_seconds=LOCKOUT_SECONDS)


def _guard_attempts(cache: RedisCacheService, nickname: str) -> None:
    current = cache.get_json(_attempts_key(nickname))
    if isinstance(current, int) and current >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много неудачных попыток. Попробуйте через 10 минут.",
        )


def _consent_state(session: Session, user_id) -> tuple[list[str], bool]:
    state = ConsentService(session).status(user_id)
    return list(state["missing"]), bool(state["distribution_answered"])


def _record_consents(
    session: Session,
    user_id,
    *,
    ip: str | None,
    distribution: dict[str, bool],
) -> None:
    consents = ConsentService(session)
    meta = {"source": "game", "ip": ip, "user_agent": "minecraft-client"}
    consents.record(user_id, DOC_OFFER, granted=True, **meta)
    consents.record(user_id, DOC_PERSONAL_DATA, granted=True, **meta)
    consents.record(user_id, DOC_DISTRIBUTION, granted=True, options=distribution, **meta)


@router.get("/account/{nickname}", response_model=GameAccountStateResponse)
def account_state(
    nickname: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> GameAccountStateResponse:
    """Is this nickname known, and what does the player still owe us?"""

    raw, _ = normalize_minecraft_nickname(nickname)
    account = _find_account(session, nickname)
    if account is None or account.user is None:
        return GameAccountStateResponse(registered=False, minecraft_nickname=raw)

    missing, distribution_answered = _consent_state(session, account.user_id)
    return GameAccountStateResponse(
        registered=True,
        minecraft_nickname=account.minecraft_nickname,
        account_active=bool(account.user.is_active),
        email_verified=bool(account.user.email_verified),
        consents_missing=missing,
        distribution_answered=distribution_answered,
    )


@router.post("/login", response_model=GameLoginResponse)
def game_login(
    payload: GameLoginRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GameLoginResponse:
    cache = RedisCacheService()
    _guard_attempts(cache, payload.minecraft_nickname)

    account = _find_account(session, payload.minecraft_nickname)
    user = account.user if account else None
    if user is None or not verify_password(payload.password, user.password_hash):
        _register_failure(cache, payload.minecraft_nickname)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный пароль.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=translate_user_message("account is disabled"),
        )

    cache.delete(_attempts_key(payload.minecraft_nickname))
    PlayerActivityService(session).record(user_id=user.id, server_id=server.id, client=CLIENT_EXTERNAL)
    session.commit()
    missing, distribution_answered = _consent_state(session, user.id)
    return GameLoginResponse(
        user_id=user.id,
        minecraft_nickname=account.minecraft_nickname,
        email_verified=bool(user.email_verified),
        consents_missing=missing,
        distribution_answered=distribution_answered,
    )


@router.post("/register", response_model=GameLoginResponse, status_code=status.HTTP_201_CREATED)
def game_register(
    payload: GameRegisterRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GameLoginResponse:
    if not (payload.accept_offer and payload.accept_personal_data):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Чтобы создать аккаунт, примите условия оферты и согласие на обработку персональных данных.",
        )

    service = _auth_service(session)
    # The site login is not asked for in game: the nickname doubles as it, and a
    # collision (someone took that login on the site without owning the nickname)
    # falls back to a suffixed login. The player signs in with their nickname in
    # game and with their email on the site, so they never have to know it.
    login_candidates = [payload.minecraft_nickname] + [f"{payload.minecraft_nickname}{n}" for n in range(2, 12)]
    last_error: ConflictError | None = None
    for candidate in login_candidates:
        try:
            user, account = service.register_user(
                site_login=candidate,
                minecraft_nickname=payload.minecraft_nickname,
                email=payload.email,
                password=payload.password,
            )
            break
        except ConflictError as exc:
            if "site_login" not in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=translate_user_message(str(exc)),
                ) from exc
            last_error = exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=translate_user_message(str(exc)),
            ) from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=translate_user_message(str(last_error)),
        )

    # Remember that this account was born in game, and on which server.
    account.registration_source = "game"
    account.registration_server_id = server.id

    _record_consents(
        session,
        user.id,
        ip=payload.ip,
        distribution={
            "profile": payload.distribution_profile,
            "map": payload.distribution_map,
            "purchases": payload.distribution_purchases,
        },
    )
    PlayerActivityService(session).record(user_id=user.id, server_id=server.id, client=CLIENT_EXTERNAL)
    session.commit()

    missing, distribution_answered = _consent_state(session, user.id)
    return GameLoginResponse(
        user_id=user.id,
        minecraft_nickname=account.minecraft_nickname,
        email_verified=bool(user.email_verified),
        consents_missing=missing,
        distribution_answered=distribution_answered,
    )


@router.post("/consents", response_model=GameLoginResponse)
def game_consents(
    payload: GameConsentRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> GameLoginResponse:
    """Accept the required documents from the in-game window.

    Used for accounts created before the current document version — the plugin
    shows this window right after a successful login and keeps the player frozen
    until it comes back accepted.
    """

    if not (payload.accept_offer and payload.accept_personal_data):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Без принятия оферты и согласия на обработку данных играть нельзя.",
        )

    account = _find_account(session, payload.minecraft_nickname)
    if account is None or account.user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аккаунт не найден.")

    _record_consents(
        session,
        account.user_id,
        ip=payload.ip,
        distribution={
            "profile": payload.distribution_profile,
            "map": payload.distribution_map,
            "purchases": payload.distribution_purchases,
        },
    )
    session.commit()

    missing, distribution_answered = _consent_state(session, account.user_id)
    return GameLoginResponse(
        user_id=account.user_id,
        minecraft_nickname=account.minecraft_nickname,
        email_verified=bool(account.user.email_verified),
        consents_missing=missing,
        distribution_answered=distribution_answered,
    )


@router.post("/seen", response_model=GameLoginResponse)
def game_seen(
    payload: GameSeenRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GameLoginResponse:
    """Counts a login that skipped the password window (kept session or launcher ticket).

    Without this the admin panel would only ever see the logins where a password was
    actually typed, and a player who never gets asked again would look inactive.
    """

    account = _find_account(session, payload.minecraft_nickname)
    if account is None or account.user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аккаунт не найден.")

    client = CLIENT_LAUNCHER if payload.client == CLIENT_LAUNCHER else CLIENT_EXTERNAL
    PlayerActivityService(session).record(user_id=account.user_id, server_id=server.id, client=client)
    session.commit()

    missing, distribution_answered = _consent_state(session, account.user_id)
    return GameLoginResponse(
        user_id=account.user_id,
        minecraft_nickname=account.minecraft_nickname,
        email_verified=bool(account.user.email_verified),
        consents_missing=missing,
        distribution_answered=distribution_answered,
    )


@router.post("/launcher-ticket", response_model=GameLoginResponse)
def game_launcher_ticket(
    payload: GameLauncherTicketRequest,
    server: Annotated[GameServer, Depends(require_game_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GameLoginResponse:
    """Recognises a player who came through our launcher, without a mod in the client.

    A modded server gets the ticket itself from the auth-bridge mod. A plugin server
    cannot: a vanilla client carries nothing but its nickname. So the launcher's ticket
    is matched here by nickname plus the address it was issued to, and consumed the same
    way — one use, and it expires on its own. Any new plugin server gets this for free:
    the ticket is already scoped to the server by the secret the plugin authenticates
    with, so nothing has to be set up per server.
    """

    account = _find_account(session, payload.minecraft_nickname)
    if account is None or account.user is None or not account.user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аккаунт не найден.")

    _, normalized = normalize_minecraft_nickname(payload.minecraft_nickname)
    query = select(PlayTicket).where(
        PlayTicket.server_id == server.id,
        PlayTicket.user_id == account.user_id,
        PlayTicket.consumed_at.is_(None),
        PlayTicket.expires_at > utc_now(),
    )
    # A label read from the address proves the launcher itself sent this player: it is
    # a secret only that launcher was given. Without one we fall back to matching the
    # address the ticket was taken from, which a VPN or a shared LAN can break.
    by_label = bool(payload.label)
    if by_label:
        query = query.where(PlayTicket.hostname_label == payload.label)

    ticket = session.execute(query.order_by(PlayTicket.issued_at.desc()).with_for_update()).scalars().first()

    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Активный билет лаунчера не найден.")

    _, ticket_nick = normalize_minecraft_nickname(ticket.minecraft_nickname)
    if ticket_nick != normalized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Билет выдан другому нику.")

    # Only a ticket taken moments ago counts here. Tickets live for a day so the
    # launcher can keep one around, but "the player our launcher just sent" is a
    # question about the last few minutes.
    if ticket.issued_at < utc_now() - timedelta(minutes=LAUNCHER_TICKET_WINDOW_MINUTES):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Билет лаунчера устарел.")

    # The address must match the one the launcher asked from — otherwise knowing a
    # nickname would be enough to ride someone else's ticket. Two addresses inside the
    # same private network count as a match: when the player and the server share a LAN,
    # the launcher's request and the game connection arrive from different local
    # addresses (router, hairpin NAT) even though it is the same person.
    if not by_label and ticket.issued_ip and payload.ip and not _same_origin(ticket.issued_ip, payload.ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Билет выдан с другого адреса.")

    ticket.consumed_at = utc_now()
    PlayerActivityService(session).record(
        user_id=account.user_id, server_id=server.id, client=CLIENT_LAUNCHER
    )
    session.commit()

    missing, distribution_answered = _consent_state(session, account.user_id)
    return GameLoginResponse(
        user_id=account.user_id,
        minecraft_nickname=account.minecraft_nickname,
        email_verified=bool(account.user.email_verified),
        consents_missing=missing,
        distribution_answered=distribution_answered,
    )
