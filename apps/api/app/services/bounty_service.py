from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models.bounty import Bounty
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.bounty import (
    BountyActionResponse,
    BountyBoardEntry,
    BountyBoardResponse,
    BountyClaimRequest,
    BountyPlaceRequest,
)


def _norm(nick: str) -> str:
    return nick.strip().lower()


class BountyService:
    """Diamond bounties on player heads. Placements stack per target; a kill claims
    them all at once and sums the payout. Diamonds are physical (handled by the mod);
    this only tracks the pledged amounts."""

    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def _user_id_by_nick(self, normalized: str) -> UUID | None:
        return self.session.scalar(
            select(PlayerAccount.user_id).where(
                PlayerAccount.minecraft_nickname_normalized == normalized
            )
        )

    def _open_total(self, target_normalized: str) -> int:
        return int(
            self.session.scalar(
                select(func.coalesce(func.sum(Bounty.amount), 0)).where(
                    Bounty.server_id == self.server_id,
                    Bounty.target_nick_normalized == target_normalized,
                    Bounty.status == "open",
                )
            )
            or 0
        )

    def place(self, req: BountyPlaceRequest) -> BountyActionResponse:
        target_norm = _norm(req.target_nick)
        placer_norm = _norm(req.placed_by_nick)
        if req.amount <= 0:
            return BountyActionResponse(ok=False, error="amount must be positive")
        if target_norm == placer_norm:
            return BountyActionResponse(ok=False, error="cannot place a bounty on yourself")

        bounty = Bounty(
            server_id=self.server_id,
            target_nick=req.target_nick,
            target_nick_normalized=target_norm,
            target_user_id=self._user_id_by_nick(target_norm),
            placed_by_nick=req.placed_by_nick,
            placed_by_user_id=self._user_id_by_nick(placer_norm),
            amount=req.amount,
            status="open",
        )
        self.session.add(bounty)
        self.session.flush()
        return BountyActionResponse(ok=True, total_amount=self._open_total(target_norm))

    def claim(self, req: BountyClaimRequest) -> BountyActionResponse:
        target_norm = _norm(req.target_nick)
        killer_norm = _norm(req.killer_nick)
        # Suicide / self-kill never pays out (anti-farm).
        if target_norm == killer_norm:
            return BountyActionResponse(ok=True, total_amount=0)

        open_bounties = list(
            self.session.scalars(
                select(Bounty).where(
                    Bounty.server_id == self.server_id,
                    Bounty.target_nick_normalized == target_norm,
                    Bounty.status == "open",
                )
            )
        )
        if not open_bounties:
            return BountyActionResponse(ok=True, total_amount=0)

        killer_user_id = self._user_id_by_nick(killer_norm)
        now = datetime.now(timezone.utc)
        total = 0
        for bounty in open_bounties:
            bounty.status = "claimed"
            bounty.killer_nick = req.killer_nick
            bounty.killer_user_id = killer_user_id
            bounty.claimed_at = now
            total += bounty.amount
        return BountyActionResponse(ok=True, total_amount=total)

    def board(self) -> BountyBoardResponse:
        rows = self.session.execute(
            select(
                Bounty.target_nick,
                func.sum(Bounty.amount).label("total"),
                func.count(Bounty.id).label("cnt"),
                func.max(Bounty.updated_at).label("last"),
            )
            .where(Bounty.server_id == self.server_id, Bounty.status == "open")
            .group_by(Bounty.target_nick_normalized, Bounty.target_nick)
            .order_by(func.sum(Bounty.amount).desc())
        ).all()
        return BountyBoardResponse(
            bounties=[
                BountyBoardEntry(
                    target_nick=r.target_nick,
                    total_amount=int(r.total),
                    contributor_count=int(r.cnt),
                    last_updated=r.last,
                )
                for r in rows
            ]
        )
