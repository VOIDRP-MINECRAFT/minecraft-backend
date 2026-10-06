"""The Monday digest of each external server, in Telegram (cron, Mondays 10:00 MSK).

    .venv/bin/python -m apps.worker.integration_digest [--dry-run]

To the people running the server (``integration.view``, linked Telegram, ``digest`` on): the
week's uptime, incidents and downtime, peak online, average TPS, connection grade, waiting
updates and what to do. Platform admins get one message with every external server. Once per
ISO week per person and server (``integration_notices`` kind ``digest``); also to the server's
Discord webhook when one is set.
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import select

import apps.api.app.models  # noqa: F401 — the full ORM graph
from apps.api.app.core import integration_brief as brief
from apps.api.app.core import integration_notices as notices
from apps.api.app.core.security import utc_now
from apps.api.app.db import SessionLocal
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User

log = logging.getLogger("integration_digest")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the messages instead of sending")
    args = ap.parse_args()
    year, week, _ = utc_now().isocalendar()
    ref = f"{year}-W{week:02d}"
    sent = 0
    with SessionLocal() as session:
        servers = session.scalars(select(GameServer).where(GameServer.is_external.is_(True))
                                  .order_by(GameServer.sort_order, GameServer.name)).all()
        texts = {}
        for server in servers:
            data = brief.overview(session, server)
            texts[server.id] = (server, data, brief.digest(session, server, data))
            if not args.dry_run:
                from apps.api.app.core import integration_discord

                sent += int(integration_discord.digest(server, ref, texts[server.id][2]))
            for user in notices.recipients(session, server):
                if not notices.prefs(user).get("digest", True):
                    continue
                if args.dry_run:
                    print(f"--- to {user.site_login} ---\n{texts[server.id][2]}\n")
                    continue
                if notices._once(session, server, user, "digest", ref) is None:
                    continue
                ok = notices._send(user.telegram_user_id, texts[server.id][2], brief.links(server, data))
                session.commit()
                sent += int(ok)
        if texts:
            admins = session.scalars(select(User).where(User.is_admin.is_(True), User.is_active.is_(True),
                                                        User.telegram_user_id.is_not(None))).all()
            body = "\n\n".join(t for _, _, t in texts.values())
            text = f"📅 <b>Неделя внешних серверов</b>\n\n{body}"
            for admin in admins:
                if not notices.prefs(admin).get("digest", True):
                    continue
                if args.dry_run:
                    print(f"--- to admin {admin.site_login} ---\n{text}\n")
                    continue
                first = next(iter(texts.values()))[0]
                if notices._once(session, first, admin, "digest_all", ref) is None:
                    continue
                ok = notices._send(admin.telegram_user_id, text[:4000],
                                   [("Все серверы в админке", f"{(brief._site())}/admin/integration")])
                session.commit()
                sent += int(ok)
    log.info("digest %s: sent %d", ref, sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
