"""Staff action audit trail — a single ``record_audit`` helper the action
endpoints call to append a row to ``admin_audit_log``.

Design goals:
- **Never break the action.** Audit is best-effort: any failure here is
  swallowed so a logging hiccup can't 500 a kick/ban/price change.
- **Self-contained.** Callers pass the acting ``User`` (or ``None`` for a
  secret/system action); we denormalize a display name so the row is readable
  even after the user is renamed or deleted.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from apps.api.app.models.admin_audit_log import AdminAuditLog

logger = logging.getLogger(__name__)


def actor_name_of(user: Any) -> str:
    if user is None:
        return "system"
    return getattr(user, "site_login", None) or getattr(user, "email", None) or "staff"


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    # Trust the proxy's forwarded chain first (nginx sets X-Forwarded-For).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else None)


def record_audit(
    session: Session,
    *,
    category: str,
    action: str,
    actor: Any = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_label: str | None = None,
    server_id: UUID | None = None,
    meta: dict | None = None,
    request: Request | None = None,
    ip: str | None = None,
    commit: bool = True,
) -> None:
    """Append one audit row. Best-effort — swallows all errors."""
    try:
        row = AdminAuditLog(
            actor_user_id=getattr(actor, "id", None),
            actor_name=actor_name_of(actor)[:120],
            category=category[:48],
            action=action[:64],
            target_type=(target_type[:48] if target_type else None),
            target_id=(str(target_id)[:120] if target_id is not None else None),
            target_label=(target_label[:200] if target_label else None),
            server_id=server_id,
            meta=meta,
            ip=(ip or client_ip(request)),
        )
        session.add(row)
        if commit:
            session.commit()
    except Exception:  # noqa: BLE001 — auditing must never break the action
        logger.exception("audit log write failed (category=%s action=%s)", category, action)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
