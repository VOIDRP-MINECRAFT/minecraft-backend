from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core.security import generate_opaque_token, hash_opaque_token, utc_now
from apps.api.app.models.play_ticket import PlayTicket
from apps.api.app.models.user import User
from apps.api.app.utils.normalization import normalize_minecraft_nickname


def _compute_launcher_proof(raw_ticket: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        raw_ticket.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class PlayTicketError(Exception):
    pass


class PlayTicketValidationError(PlayTicketError):
    pass


@dataclass(slots=True)
class IssuedPlayTicket:
    ticket: str
    expires_at: datetime
    minecraft_nickname: str
    ttl_seconds: int


@dataclass(slots=True)
class ConsumedPlayTicket:
    user_id: UUID
    minecraft_nickname: str
    legacy_auth_enabled: bool
    expires_at: datetime


class PlayTicketService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def issue_for_user(
        self,
        *,
        user: User,
        launcher_version: str,
        launcher_platform: str,
    ) -> IssuedPlayTicket:
        if user.player_account is None:
            raise PlayTicketValidationError("player account is not linked")

        self._expire_existing_tickets(user.id)

        raw_ticket = generate_opaque_token()
        now = utc_now()
        expires_at = now + timedelta(minutes=self.settings.play_ticket_expire_minutes)

        ticket = PlayTicket(
            user_id=user.id,
            minecraft_nickname=user.player_account.minecraft_nickname,
            ticket_hash=hash_opaque_token(raw_ticket),
            launcher_version=launcher_version.strip()[:32] or "unknown",
            launcher_platform=launcher_platform.strip()[:64] or "unknown",
            issued_at=now,
            expires_at=expires_at,
            consumed_at=None,
        )
        self.session.add(ticket)
        self.session.commit()

        ttl_seconds = int((expires_at - now).total_seconds())
        return IssuedPlayTicket(
            ticket=raw_ticket,
            expires_at=expires_at,
            minecraft_nickname=user.player_account.minecraft_nickname,
            ttl_seconds=max(ttl_seconds, 0),
        )

    def consume(
        self,
        *,
        raw_ticket: str,
        player_name: str,
        launcher_proof: str | None = None,
    ) -> ConsumedPlayTicket:
        ticket_hash = hash_opaque_token(raw_ticket)
        play_ticket = self.session.execute(
            select(PlayTicket).where(PlayTicket.ticket_hash == ticket_hash).with_for_update()
        ).scalar_one_or_none()

        if play_ticket is None:
            raise PlayTicketValidationError("play ticket is invalid")

        now = utc_now()
        if play_ticket.expires_at <= now:
            raise PlayTicketValidationError("play ticket is expired")

        # Reject already-consumed tickets (prevent replay attacks)
        if play_ticket.consumed_at is not None:
            raise PlayTicketValidationError("play ticket is already used")

        requested_name_raw, requested_name_normalized = normalize_minecraft_nickname(player_name)
        _, ticket_name_normalized = normalize_minecraft_nickname(play_ticket.minecraft_nickname)
        if requested_name_normalized != ticket_name_normalized:
            raise PlayTicketValidationError("player name does not match play ticket")

        user = self.session.execute(
            select(User).where(User.id == play_ticket.user_id)
        ).scalar_one_or_none()

        if user is None or not user.is_active or user.player_account is None:
            raise PlayTicketValidationError("ticket user is not available")

        # Validate launcher HMAC proof when a secret is configured
        if self.settings.launcher_hmac_secret:
            expected_proof = _compute_launcher_proof(raw_ticket, self.settings.launcher_hmac_secret)
            if not launcher_proof or not hmac.compare_digest(launcher_proof, expected_proof):
                raise PlayTicketValidationError("launcher proof is invalid")

        play_ticket.consumed_at = now
        self.session.commit()

        return ConsumedPlayTicket(
            user_id=user.id,
            minecraft_nickname=requested_name_raw,
            legacy_auth_enabled=user.player_account.legacy_auth_enabled,
            expires_at=play_ticket.expires_at,
        )

    def _expire_existing_tickets(self, user_id: UUID) -> None:
        now = utc_now()
        active_tickets = self.session.execute(
            select(PlayTicket).where(
                PlayTicket.user_id == user_id,
                PlayTicket.expires_at > now,
            ).with_for_update()
        ).scalars().all()
        if not active_tickets:
            return

        for ticket in active_tickets:
            ticket.expires_at = now
        self.session.flush()
