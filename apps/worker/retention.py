"""Keeps the retention terms the privacy policy promises (void-rp.ru/privacy). Run once a
day from cron:

    10 5 * * * cd …/minecraft_backend && .venv/bin/python -m apps.worker.retention

* sign-ins («Активные входы») — deleted 12 months after they ended (signed out or expired);
  refresh tokens go with them;
* the staff action log — entries older than 12 months;
* CoreProtect (block and container history on Paper servers) — ``co purge t:365d`` over
  RCON on running servers that have it, once in 30 days.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, or_

from apps.api.app.core.security import utc_now
from apps.api.app.db import SessionLocal
from apps.api.app.models.admin_audit_log import AdminAuditLog
from apps.api.app.models.auth_device import AuthDevice
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.refresh_session import RefreshSession

log = logging.getLogger("retention")
KEEP = timedelta(days=365)
COREPROTECT_EVERY = 30 * 86400
STATE = Path(__file__).resolve().parents[2] / "data" / "retention_state.json"


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))


def purge_database() -> None:
    cutoff = utc_now() - KEEP
    with SessionLocal() as s:
        devices = s.execute(delete(AuthDevice).where(or_(
            AuthDevice.revoked_at < cutoff,
            (AuthDevice.revoked_at.is_(None) & (AuthDevice.expires_at < cutoff)),
        ))).rowcount
        tokens = s.execute(delete(RefreshSession).where(RefreshSession.device_id.is_(None), or_(
            RefreshSession.revoked_at < cutoff, RefreshSession.expires_at < cutoff,
        ))).rowcount
        audit = s.execute(delete(AdminAuditLog).where(AdminAuditLog.created_at < cutoff)).rowcount
        s.commit()
    log.info("retention: sign-ins %s, old tokens %s, staff log %s deleted", devices, tokens, audit)


def purge_coreprotect() -> None:
    from apps.api.app.core import server_ops
    from apps.api.app.core.server_changes import running

    state = _state()
    with SessionLocal() as s:
        servers = s.query(GameServer).all()
        for server in servers:
            if not server.data_dir or not server.rcon_port:
                continue
            plugins = Path(server.data_dir) / "plugins"
            if not any(plugins.glob("CoreProtect*.jar")):
                continue
            key = f"coreprotect:{server.slug}"
            if time.time() - state.get(key, 0) < COREPROTECT_EVERY:
                continue
            try:
                if not running(server):
                    continue
                out = server_ops.rcon_command(server, "co purge t:365d", timeout=120)
                state[key] = time.time()
                log.info("retention: CoreProtect purge on %s: %s", server.slug, (out or "").strip()[:200])
            except Exception as exc:  # noqa: BLE001 — try again tomorrow
                log.warning("retention: CoreProtect purge on %s failed: %s", server.slug, exc)
    _save(state)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    purge_database()
    purge_coreprotect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
