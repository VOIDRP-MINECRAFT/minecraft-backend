"""Second-day return worker (cron, every minute).

    .venv/bin/python -m apps.worker.player_return

Gives queued welcome messages and second-day rewards to players in game (core/retention.py)
and sends the one-time Telegram reminder to newcomers who have not come back.
"""
from __future__ import annotations

import logging

import apps.api.app.models  # noqa: F401 — the full ORM graph
from apps.api.app.core import retention
from apps.api.app.db import SessionLocal


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with SessionLocal() as session:
        done = retention.run_due(session)
        sent = retention.send_reminders(session)
    if done or sent:
        logging.getLogger("player_return").info("deliveries processed: %d, reminders sent: %d", done, sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
