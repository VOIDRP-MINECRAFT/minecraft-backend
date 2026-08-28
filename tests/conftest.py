from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


# Several models carry JSONB columns (game_servers.features / .news_channels,
# users.staff_permissions, ...). The SQLite dialect used by the tests cannot
# render that type, so emit plain JSON there and let the tables be created.
# Postgres DDL is untouched — this only teaches the SQLite compiler.
@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(type_, compiler, **kw) -> str:  # noqa: ARG001
    return "JSON"
