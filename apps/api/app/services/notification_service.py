"""Per-account in-game notifications (HUD overlay)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_game_settings import PlayerGameSettings
from apps.api.app.models.player_notification import PlayerNotification

# Recent, undismissed notifications shown in the HUD feed.
FEED_LIMIT = 12

# Notification types a player may opt out of (chatty ones). Important types
# (join requests, approvals, season rewards, alliance votes) are always delivered.
MUTABLE_NOTIFICATION_TYPES = {"market_sold", "achievement", "weekly_challenge", "login_streak", "battlepass"}


class NotificationService:
    def __init__(self, session: Session, server_id: UUID):
        self.session = session
        self.server_id = server_id

    def create(
        self,
        *,
        user_id: UUID,
        type: str,
        title: str,
        body: str | None = None,
        icon: str | None = None,
        accent: str | None = None,
        action_type: str | None = None,
        action_payload: str | None = None,
        action_label: str | None = None,
    ) -> PlayerNotification | None:
        if self._is_muted(user_id, type):
            return None
        note = PlayerNotification(
            server_id=self.server_id,
            user_id=user_id,
            type=type[:48],
            title=title[:160],
            body=body[:400] if body else None,
            icon=icon[:48] if icon else None,
            accent=accent[:16] if accent else None,
            action_type=action_type[:24] if action_type else None,
            action_payload=action_payload[:200] if action_payload else None,
            action_label=action_label[:48] if action_label else None,
        )
        self.session.add(note)
        self.session.flush()
        return note

    def _is_muted(self, user_id: UUID, notif_type: str) -> bool:
        if notif_type not in MUTABLE_NOTIFICATION_TYPES:
            return False
        stored = self.session.execute(
            select(PlayerGameSettings.settings).where(
                PlayerGameSettings.server_id == self.server_id,
                PlayerGameSettings.user_id == user_id,
            )
        ).scalar_one_or_none()
        if not isinstance(stored, dict):
            return False
        return notif_type in (stored.get("muted_notifications") or [])

    def create_for_nick(self, nickname: str, **kwargs) -> PlayerNotification | None:
        """Create a notification addressed by minecraft nickname. Returns None if no such account."""
        norm = (nickname or "").strip().lower()
        if not norm:
            return None
        player = self.session.execute(
            select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == norm)
        ).scalar_one_or_none()
        if player is None:
            return None
        return self.create(user_id=player.user_id, **kwargs)

    def feed(self, user_id: UUID) -> list[PlayerNotification]:
        """Recent UNSEEN, undismissed notifications, newest first (one-shot toasts)."""
        return list(
            self.session.execute(
                select(PlayerNotification)
                .where(
                    PlayerNotification.server_id == self.server_id,
                    PlayerNotification.user_id == user_id,
                    PlayerNotification.seen_at.is_(None),
                    PlayerNotification.dismissed_at.is_(None),
                )
                .order_by(PlayerNotification.created_at.desc())
                .limit(FEED_LIMIT)
            ).scalars()
        )

    def history(self, user_id: UUID, limit: int = 40) -> list[PlayerNotification]:
        """Recent undismissed notifications (seen or unseen), newest first — the in-game
        notification center. Unlike :meth:`feed`, this does NOT mark anything seen."""
        return list(
            self.session.execute(
                select(PlayerNotification)
                .where(
                    PlayerNotification.server_id == self.server_id,
                    PlayerNotification.user_id == user_id,
                    PlayerNotification.dismissed_at.is_(None),
                )
                .order_by(PlayerNotification.created_at.desc())
                .limit(max(1, min(limit, 100)))
            ).scalars()
        )

    def dismiss(self, notification_id: UUID, user_id: UUID) -> bool:
        res = self.session.execute(
            update(PlayerNotification)
            .where(
                PlayerNotification.id == notification_id,
                PlayerNotification.user_id == user_id,
                PlayerNotification.server_id == self.server_id,
                PlayerNotification.dismissed_at.is_(None),
            )
            .values(dismissed_at=datetime.now(timezone.utc))
        )
        return res.rowcount > 0

    def mark_seen(self, user_id: UUID, ids: list[UUID]) -> None:
        if not ids:
            return
        self.session.execute(
            update(PlayerNotification)
            .where(
                PlayerNotification.user_id == user_id,
                PlayerNotification.server_id == self.server_id,
                PlayerNotification.id.in_(ids),
                PlayerNotification.seen_at.is_(None),
            )
            .values(seen_at=datetime.now(timezone.utc))
        )
