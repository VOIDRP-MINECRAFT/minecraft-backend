"""Recording and reading user consents (see models/user_consent.py and core/legal_documents.py)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.legal_documents import (
    DISTRIBUTION_CATEGORIES,
    DOC_DISTRIBUTION,
    LEGAL_VERSIONS,
    REQUIRED_DOCUMENTS,
)
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.user_consent import UserConsent


def normalize_distribution(options: dict | None) -> dict[str, bool]:
    options = options or {}
    return {key: bool(options.get(key)) for key in DISTRIBUTION_CATEGORIES}


class ConsentService:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        user_id: UUID,
        document: str,
        *,
        granted: bool,
        source: str,
        options: dict | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> UserConsent:
        row = UserConsent(
            user_id=user_id,
            document=document,
            version=LEGAL_VERSIONS[document],
            granted=granted,
            options=normalize_distribution(options) if document == DOC_DISTRIBUTION else None,
            source=source[:32],
            ip=(ip or None) and ip[:64],
            user_agent=(user_agent or None) and user_agent[:512],
        )
        self.session.add(row)
        self.session.flush()
        return row

    def latest(self, user_id: UUID) -> dict[str, UserConsent]:
        rows = self.session.execute(
            select(UserConsent).where(UserConsent.user_id == user_id).order_by(UserConsent.created_at.asc())
        ).scalars().all()
        out: dict[str, UserConsent] = {}
        for row in rows:
            out[row.document] = row
        return out

    def status(self, user_id: UUID) -> dict:
        latest = self.latest(user_id)
        docs = {}
        for document, version in LEGAL_VERSIONS.items():
            row = latest.get(document)
            docs[document] = {
                "current_version": version,
                "accepted_version": row.version if row and row.granted else None,
                "accepted_at": row.created_at.isoformat() if row and row.granted else None,
            }
        missing = [d for d in REQUIRED_DOCUMENTS if not (latest.get(d) and latest[d].granted and latest[d].version == LEGAL_VERSIONS[d])]
        dist = latest.get(DOC_DISTRIBUTION)
        return {
            "documents": docs,
            "missing": missing,
            # The distribution choice is asked once per edition; until answered nothing is made public.
            "distribution_answered": bool(dist and dist.version == LEGAL_VERSIONS[DOC_DISTRIBUTION]),
            "distribution": normalize_distribution(dist.options if dist and dist.granted else None),
        }

    def distribution_allowed(self, user_id: UUID, category: str) -> bool:
        return self.status_distribution(user_id).get(category, False)

    def status_distribution(self, user_id: UUID) -> dict[str, bool]:
        row = self.session.execute(
            select(UserConsent)
            .where(UserConsent.user_id == user_id, UserConsent.document == DOC_DISTRIBUTION)
            .order_by(UserConsent.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return normalize_distribution(row.options if row and row.granted else None)

    def nicknames_allowing(self, category: str) -> set[str]:
        """Normalized nicknames of accounts whose latest distribution consent allows ``category``."""
        rows = self.session.execute(
            select(UserConsent.user_id, UserConsent.options, UserConsent.granted, UserConsent.created_at)
            .where(UserConsent.document == DOC_DISTRIBUTION)
            .order_by(UserConsent.created_at.asc())
        ).all()
        latest: dict[UUID, tuple] = {}
        for user_id, options, granted, _ in rows:
            latest[user_id] = (options, granted)
        allowed_ids = [uid for uid, (options, granted) in latest.items() if granted and normalize_distribution(options).get(category)]
        if not allowed_ids:
            return set()
        nicks = self.session.execute(
            select(PlayerAccount.minecraft_nickname_normalized).where(PlayerAccount.user_id.in_(allowed_ids))
        ).scalars().all()
        return {n for n in nicks if n}

    def missing_for_nickname(self, nickname: str) -> tuple[UUID | None, list[str]]:
        norm = (nickname or "").strip().lower()
        player = self.session.execute(
            select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == norm)
        ).scalar_one_or_none()
        if player is None:
            return None, []
        return player.user_id, self.status(player.user_id)["missing"]
