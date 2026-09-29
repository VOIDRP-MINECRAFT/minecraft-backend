from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.core.staff_authority import rank
from apps.api.app.dependencies.admin import PermittedServers, get_current_staff_user, require_permission_somewhere
from apps.api.app.models.admin_audit_log import AdminAuditLog
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User

router = APIRouter(
    prefix="/admin/audit",
    tags=["admin", "audit"],
)


@router.get("")
def list_audit(
    session: Annotated[Session, Depends(get_db_session)],
    where: Annotated[PermittedServers, Depends(require_permission_somewhere("audit.view"))],
    me: Annotated[User, Depends(get_current_staff_user)],
    q: Annotated[str | None, Query(max_length=120)] = None,
    category: Annotated[str | None, Query(max_length=48)] = None,
    days: Annotated[int, Query(ge=0, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Paginated staff-action log, newest first. ``days=0`` = no time limit."""
    conds = []
    # Per server: only the entries of servers this person may audit; entries tied to
    # no server (platform-wide actions) only with the permission on every server.
    if not where.all:
        conds.append(AdminAuditLog.server_id.in_(where.ids))
    # Nobody sees what people senior to them did (owner > platform admins > admins of
    # servers > by highest role). Their own entries and system ones stay visible.
    if not me.is_owner:
        mine = rank(me)
        staff = session.scalars(select(User).where(or_(User.is_admin.is_(True), User.is_moderator.is_(True)))).all()
        senior = [u.id for u in staff if u.id != me.id and rank(u) > mine]
        if senior:
            conds.append(or_(AdminAuditLog.actor_user_id.is_(None), AdminAuditLog.actor_user_id.notin_(senior)))
    if days:
        conds.append(AdminAuditLog.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
    if category:
        conds.append(AdminAuditLog.category == category)
    if q:
        like = f"%{q.strip()}%"
        conds.append(
            or_(
                AdminAuditLog.actor_name.ilike(like),
                AdminAuditLog.action.ilike(like),
                AdminAuditLog.target_label.ilike(like),
                AdminAuditLog.target_id.ilike(like),
            )
        )

    total = session.scalar(select(func.count()).select_from(AdminAuditLog).where(*conds)) or 0
    rows = session.scalars(
        select(AdminAuditLog).where(*conds).order_by(AdminAuditLog.created_at.desc()).offset(offset).limit(limit)
    ).all()

    # Resolve server names in one query for the page.
    srv_ids = {r.server_id for r in rows if r.server_id}
    srv_names: dict = {}
    if srv_ids:
        for sid, name in session.execute(
            select(GameServer.id, GameServer.name).where(GameServer.id.in_(srv_ids))
        ).all():
            srv_names[sid] = name

    items = [
        {
            "id": str(r.id),
            "actor_name": r.actor_name,
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "category": r.category,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "target_label": r.target_label,
            "server_id": str(r.server_id) if r.server_id else None,
            "server_name": srv_names.get(r.server_id),
            "meta": r.meta,
            "ip": r.ip,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

    # Distinct categories for the filter dropdown (cheap, small cardinality).
    categories = [
        c for (c,) in session.execute(select(AdminAuditLog.category).distinct().order_by(AdminAuditLog.category)).all()
    ]

    return {"items": items, "total": total, "categories": categories}
