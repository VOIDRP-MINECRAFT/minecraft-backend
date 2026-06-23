from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.api.app.core.rcon_client import send_rcon_command
from apps.api.app.models.battlepass import BattlePassPremium, BattlePassProgress
from apps.api.app.schemas.battlepass import (
    AdminBattlePassPlayerInfo,
    BattlePassLeaderboardEntry,
    BattlePassLeaderboardResponse,
    BattlePassPremiumGrantRequest,
    BattlePassPremiumListResponse,
    BattlePassPremiumResponse,
    BattlePassPremiumStatusResponse,
    BattlePassProgressUpsertRequest,
    BattlePassPublicProfileResponse,
)


class BattlePassNotFoundError(Exception):
    pass


def _to_response(record: BattlePassPremium) -> BattlePassPremiumResponse:
    now = datetime.now(timezone.utc)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return BattlePassPremiumResponse(
        minecraft_uuid=record.minecraft_uuid,
        minecraft_nickname=record.minecraft_nickname,
        expires_at=expires,
        granted_by=record.granted_by,
        note=record.note,
        is_active=expires > now,
    )


class BattlePassService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_premium_status(self, minecraft_uuid: str) -> BattlePassPremiumStatusResponse:
        record = self.session.execute(
            select(BattlePassPremium).where(
                BattlePassPremium.minecraft_uuid == minecraft_uuid
            )
        ).scalar_one_or_none()

        if record is None:
            return BattlePassPremiumStatusResponse(
                minecraft_uuid=minecraft_uuid,
                has_premium=False,
                expires_at=None,
            )

        now = datetime.now(timezone.utc)
        expires = record.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        return BattlePassPremiumStatusResponse(
            minecraft_uuid=minecraft_uuid,
            has_premium=expires > now,
            expires_at=expires,
        )

    def grant_premium(
        self,
        req: BattlePassPremiumGrantRequest,
        granted_by: str,
    ) -> BattlePassPremiumResponse:
        now = datetime.now(timezone.utc)
        new_expiry = now + timedelta(days=req.days)

        record = self.session.execute(
            select(BattlePassPremium).where(
                BattlePassPremium.minecraft_uuid == req.minecraft_uuid
            )
        ).scalar_one_or_none()

        if record is None:
            record = BattlePassPremium(
                minecraft_uuid=req.minecraft_uuid,
                minecraft_nickname=req.minecraft_nickname,
                expires_at=new_expiry,
                granted_by=granted_by,
                note=req.note,
            )
            self.session.add(record)
        else:
            current_expiry = record.expires_at
            if current_expiry.tzinfo is None:
                current_expiry = current_expiry.replace(tzinfo=timezone.utc)
            # Extend from max(current expires_at, now) + days
            base = max(current_expiry, now)
            record.expires_at = base + timedelta(days=req.days)
            record.minecraft_nickname = req.minecraft_nickname
            record.granted_by = granted_by
            if req.note is not None:
                record.note = req.note

        self.session.commit()
        self.session.refresh(record)
        expires = record.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        expiry_ms = int(expires.timestamp() * 1000)
        send_rcon_command(f"bpadmin premium sync {req.minecraft_nickname} {expiry_ms}")
        return _to_response(record)

    def revoke_premium(self, minecraft_uuid: str) -> None:
        record = self.session.execute(
            select(BattlePassPremium).where(
                BattlePassPremium.minecraft_uuid == minecraft_uuid
            )
        ).scalar_one_or_none()

        if record is None:
            raise BattlePassNotFoundError(
                f"Battle pass premium record not found for uuid={minecraft_uuid}"
            )

        nickname = record.minecraft_nickname
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.session.commit()
        send_rcon_command(f"bpadmin premium sync {nickname} 0")

    def revoke_premium_by_nick(self, nickname: str) -> None:
        """Revoke by nickname: updates DB if record found, always runs RCON."""
        record = self.session.execute(
            select(BattlePassPremium).where(
                func.lower(BattlePassPremium.minecraft_nickname) == nickname.lower()
            )
        ).scalar_one_or_none()
        if record is not None:
            record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            self.session.commit()
        send_rcon_command(f"bpadmin premium sync {nickname} 0")

    def list_active_premium(
        self, skip: int = 0, limit: int = 50
    ) -> BattlePassPremiumListResponse:
        now = datetime.now(timezone.utc)
        total = self.session.execute(
            select(func.count(BattlePassPremium.id)).where(
                BattlePassPremium.expires_at > now
            )
        ).scalar_one()

        records = self.session.execute(
            select(BattlePassPremium)
            .where(BattlePassPremium.expires_at > now)
            .order_by(BattlePassPremium.expires_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()

        return BattlePassPremiumListResponse(
            items=[_to_response(r) for r in records],
            total=total,
        )

    def list_all_premium(
        self, skip: int = 0, limit: int = 50
    ) -> BattlePassPremiumListResponse:
        total = self.session.execute(
            select(func.count(BattlePassPremium.id))
        ).scalar_one()

        records = self.session.execute(
            select(BattlePassPremium)
            .order_by(BattlePassPremium.expires_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()

        return BattlePassPremiumListResponse(
            items=[_to_response(r) for r in records],
            total=total,
        )

    def upsert_progress(self, req: BattlePassProgressUpsertRequest) -> None:
        stmt = (
            pg_insert(BattlePassProgress)
            .values(
                id=uuid4(),
                minecraft_uuid=req.minecraft_uuid,
                minecraft_nickname=req.minecraft_nickname,
                season=req.season,
                level=req.level,
                xp=req.xp,
            )
            .on_conflict_do_update(
                index_elements=["minecraft_uuid"],
                set_={
                    "minecraft_nickname": req.minecraft_nickname,
                    "season": req.season,
                    "level": req.level,
                    "xp": req.xp,
                    "updated_at": text("now()"),
                },
            )
        )
        self.session.execute(stmt)
        self.session.commit()

    def get_public_profile(self, minecraft_uuid: str) -> BattlePassPublicProfileResponse:
        progress = self.session.execute(
            select(BattlePassProgress).where(
                BattlePassProgress.minecraft_uuid == minecraft_uuid
            )
        ).scalar_one_or_none()
        premium_status = self.get_premium_status(minecraft_uuid)
        return BattlePassPublicProfileResponse(
            minecraft_uuid=minecraft_uuid,
            season=progress.season if progress else None,
            level=progress.level if progress else 1,
            xp=progress.xp if progress else 0,
            has_premium=premium_status.has_premium,
            premium_expires_at=premium_status.expires_at,
        )

    def get_public_profile_by_nick(self, nickname: str) -> BattlePassPublicProfileResponse | None:
        progress = self.session.execute(
            select(BattlePassProgress).where(
                BattlePassProgress.minecraft_nickname == nickname
            )
        ).scalar_one_or_none()
        if progress is None:
            return None
        premium_status = self.get_premium_status(progress.minecraft_uuid)
        return BattlePassPublicProfileResponse(
            minecraft_uuid=progress.minecraft_uuid,
            season=progress.season,
            level=progress.level,
            xp=progress.xp,
            has_premium=premium_status.has_premium,
            premium_expires_at=premium_status.expires_at,
        )

    def get_admin_player_info_by_nick(self, nickname: str) -> AdminBattlePassPlayerInfo:
        progress = self.session.execute(
            select(BattlePassProgress).where(
                func.lower(BattlePassProgress.minecraft_nickname) == nickname.lower()
            )
        ).scalar_one_or_none()

        premium = None
        if progress:
            premium = self.session.execute(
                select(BattlePassPremium).where(
                    BattlePassPremium.minecraft_uuid == progress.minecraft_uuid
                )
            ).scalar_one_or_none()
        else:
            # may have premium without progress (granted before first login)
            premium = self.session.execute(
                select(BattlePassPremium).where(
                    func.lower(BattlePassPremium.minecraft_nickname) == nickname.lower()
                )
            ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        expires_at: datetime | None = None
        has_premium = False
        if premium:
            exp = premium.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            expires_at = exp
            has_premium = exp > now

        return AdminBattlePassPlayerInfo(
            minecraft_uuid=progress.minecraft_uuid if progress else (premium.minecraft_uuid if premium else None),
            minecraft_nickname=nickname,
            has_premium=has_premium,
            expires_at=expires_at,
            level=progress.level if progress else 1,
            xp=progress.xp if progress else 0,
            season=progress.season if progress else None,
        )

    def get_leaderboard(self, limit: int = 50) -> BattlePassLeaderboardResponse:
        now = datetime.now(timezone.utc)
        rows = (
            self.session.execute(
                select(BattlePassProgress, BattlePassPremium)
                .outerjoin(
                    BattlePassPremium,
                    BattlePassProgress.minecraft_uuid == BattlePassPremium.minecraft_uuid,
                )
                .where(
                    BattlePassProgress.minecraft_nickname.notlike("% %"),
                    func.length(BattlePassProgress.minecraft_nickname) >= 3,
                    func.length(BattlePassProgress.minecraft_nickname) <= 16,
                )
                .order_by(BattlePassProgress.level.desc(), BattlePassProgress.xp.desc())
                .limit(limit)
            )
            .all()
        )

        entries: list[BattlePassLeaderboardEntry] = []
        for rank, (progress, premium) in enumerate(rows, 1):
            has_premium = False
            if premium is not None:
                exp = premium.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                has_premium = exp > now
            entries.append(
                BattlePassLeaderboardEntry(
                    rank=rank,
                    minecraft_nickname=progress.minecraft_nickname,
                    minecraft_uuid=progress.minecraft_uuid,
                    level=progress.level,
                    xp=progress.xp,
                    has_premium=has_premium,
                )
            )

        total = self.session.execute(
            select(func.count(BattlePassProgress.id))
        ).scalar_one()
        season = rows[0][0].season if rows else None
        return BattlePassLeaderboardResponse(season=season, entries=entries, total=total)

    def get_stats(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        total = self.session.execute(
            select(func.count(BattlePassPremium.id))
        ).scalar_one()
        active = self.session.execute(
            select(func.count(BattlePassPremium.id)).where(
                BattlePassPremium.expires_at > now
            )
        ).scalar_one()
        return {"total": total, "active": active}
