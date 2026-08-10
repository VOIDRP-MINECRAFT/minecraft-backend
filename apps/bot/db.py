from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, configure_mappers

# Reuse the API's engine/sessionmaker — the bot shares one DB with the backend.
from apps.api.app.db import SessionLocal

# Register the full ORM graph up-front. The bot doesn't run create_app(), so
# without this the User.player_skin (etc.) relationships can't resolve on the
# first query. Importing the models package + configuring mappers fails fast.
import apps.api.app.models  # noqa: E402,F401

configure_mappers()


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
