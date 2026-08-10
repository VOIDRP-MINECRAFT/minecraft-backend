from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

# Reuse the API's engine/sessionmaker — the bot shares one DB with the backend.
from apps.api.app.db import SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for a single bot operation."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
