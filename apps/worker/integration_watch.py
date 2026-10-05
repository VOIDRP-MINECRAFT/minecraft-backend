"""External servers whose required modules went quiet — and came back (cron, every 2 min).

    .venv/bin/python -m apps.worker.integration_watch

Sends the notices of ``core/integration_notices.check_health`` to the people running each
server; every outage is announced once, and so is its end.
"""
from __future__ import annotations

import logging

from apps.api.app.core import integration_notices


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sent = integration_notices.check_health()
    if sent:
        logging.getLogger("integration_watch").info("notices sent: %d", sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
