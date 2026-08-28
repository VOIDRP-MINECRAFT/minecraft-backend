from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.anticheat import AnticheatInjectionReport, AnticheatViolation
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.punishment import Punishment
from apps.api.app.models.user import User

# One aggregated "player 360" card that stitches together the account, its
# nations, anticheat history and punishments — keyed by minecraft nickname,
# the join key common to all three systems.
router = APIRouter(
    prefix="/admin/player-overview",
    tags=["admin", "players"],
    dependencies=[Depends(require_permission("players.view"))],
)


@router.get("/{nickname}")
def player_overview(
    nickname: str,
    server: Annotated[GameServer, Depends(resolve_server)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    nick = nickname.strip()
    nick_norm = nick.lower()
    out: dict = {"nickname": nick, "server_id": str(server.id), "server_name": server.name}

    # ── Account ──────────────────────────────────────────────────────────────
    account = None
    try:
        account = session.scalars(
            select(PlayerAccount).where(PlayerAccount.minecraft_nickname_normalized == nick_norm)
        ).first()
    except Exception:  # noqa: BLE001
        account = None
    if account is not None:
        user = session.get(User, account.user_id)
        out["account"] = {
            "account_id": str(account.id),
            "user_id": str(account.user_id),
            "nickname": account.minecraft_nickname,
            "site_login": getattr(user, "site_login", None),
            "email": getattr(user, "email", None),
            "is_admin": getattr(user, "is_admin", False),
            "is_moderator": getattr(user, "is_moderator", False),
            "legacy_auth_enabled": account.legacy_auth_enabled,
            "nickname_locked": account.nickname_locked,
            "created_at": account.created_at.isoformat() if account.created_at else None,
        }
    else:
        out["account"] = None

    # ── Nations (on the active server) ───────────────────────────────────────
    out["nations"] = []
    if account is not None:
        try:
            rows = session.execute(
                select(Nation.title, Nation.tag, Nation.slug, NationMember.role)
                .join(Nation, Nation.id == NationMember.nation_id)
                .where(NationMember.user_id == account.user_id, NationMember.server_id == server.id)
            ).all()
            out["nations"] = [{"name": t, "tag": tag, "slug": s, "role": r} for (t, tag, s, r) in rows]
        except Exception:  # noqa: BLE001
            out["nations"] = []

    # ── Anticheat (server-scoped, keyed by nick) ─────────────────────────────
    try:
        base = select(AnticheatViolation).where(
            AnticheatViolation.player_nick.ilike(nick), AnticheatViolation.server_id == server.id
        )
        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        total_vl = session.scalar(
            select(func.coalesce(func.sum(AnticheatViolation.vl), 0)).where(
                AnticheatViolation.player_nick.ilike(nick), AnticheatViolation.server_id == server.id
            )
        ) or 0
        unreviewed = session.scalar(
            select(func.count()).select_from(AnticheatViolation).where(
                AnticheatViolation.player_nick.ilike(nick),
                AnticheatViolation.server_id == server.id,
                AnticheatViolation.reviewed.is_(False),
            )
        ) or 0
        recent = session.scalars(
            base.order_by(AnticheatViolation.created_at.desc()).limit(8)
        ).all()
        injections = session.scalar(
            select(func.count()).select_from(AnticheatInjectionReport).where(
                AnticheatInjectionReport.player_nick.ilike(nick),
                AnticheatInjectionReport.server_id == server.id,
                AnticheatInjectionReport.agents_detected.is_(True),
            )
        ) or 0
        player_uuid = recent[0].player_uuid if recent else None
        out["anticheat"] = {
            "total_violations": total,
            "total_vl": int(total_vl),
            "unreviewed": unreviewed,
            "injection_reports": injections,
            "player_uuid": player_uuid,
            "recent": [
                {
                    "check_type": v.check_type,
                    "vl": v.vl,
                    "severity": v.severity,
                    "reviewed": v.reviewed,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in recent
            ],
        }
    except Exception:  # noqa: BLE001
        out["anticheat"] = {"total_violations": 0, "total_vl": 0, "unreviewed": 0,
                            "injection_reports": 0, "player_uuid": None, "recent": []}

    # ── Punishments (server + global) ────────────────────────────────────────
    try:
        prows = session.scalars(
            select(Punishment)
            .where(
                Punishment.player_name.ilike(nick),
                or_(Punishment.server_id == server.id, Punishment.server_id.is_(None)),
            )
            .order_by(Punishment.created_at.desc())
            .limit(30)
        ).all()
        out["punishments"] = [
            {
                "id": str(p.id),
                "type": p.type,
                "reason": p.reason,
                "issued_by_name": p.issued_by_name,
                "active": p.active,
                "effective": p.is_effective,
                "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                "created_at": p.created_at.isoformat(),
            }
            for p in prows
        ]
        out["active_punishments"] = sum(1 for p in prows if p.is_effective)
    except Exception:  # noqa: BLE001
        out["punishments"] = []
        out["active_punishments"] = 0

    return out
