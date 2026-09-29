"""Signing a device (or all of a person's devices) out: its refresh tokens stop working
at once, and the admin panel refuses its access tokens (checked by ``sid``)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.core.security import utc_now
from apps.api.app.models.auth_device import AuthDevice
from apps.api.app.models.refresh_session import RefreshSession


def revoke_devices(session: Session, user_id: UUID, *, only: UUID | None = None, keep: UUID | None = None) -> int:
    """Signs out one device (``only``), or every device of the person except ``keep``.
    Returns how many were signed out. The caller commits."""
    now = utc_now()
    q = select(AuthDevice).where(AuthDevice.user_id == user_id, AuthDevice.revoked_at.is_(None))
    if only is not None:
        q = q.where(AuthDevice.id == only)
    if keep is not None:
        q = q.where(AuthDevice.id != keep)
    devices = session.scalars(q).all()
    ids = [d.id for d in devices]
    for d in devices:
        d.revoked_at = now
    rs = update(RefreshSession).where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
    if only is not None or keep is not None:
        rs = rs.where(RefreshSession.device_id.in_(ids or [None]))
    session.execute(rs.values(revoked_at=now, last_used_at=now))
    return len(ids)
