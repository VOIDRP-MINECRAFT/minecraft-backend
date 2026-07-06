from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.api.routes import servers as servers_route
from apps.api.app.config import get_settings
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_server
from apps.api.app.main import create_app
from apps.api.app.models.game_server import GameServer
from apps.api.app.schemas.game_server import GameServerStatus


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Only create the game_servers table (avoids JSONB models incompatible with SQLite).
    db_path = tmp_path / "servers.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    GameServer.__table__.create(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Never hit the network in tests.
    monkeypatch.setattr(
        servers_route, "_ping_status", lambda host, port: GameServerStatus(online=False)
    )

    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db
    admin_secret = get_settings().admin_api_secret

    with TestClient(app) as client:
        yield client, admin_secret, TestingSessionLocal

    app.dependency_overrides.clear()


def _create(client: TestClient, admin_secret: str, slug: str, **overrides) -> dict:
    payload = {"slug": slug, "name": slug.upper(), "host": f"{slug}.example.com", **overrides}
    resp = client.post(
        "/api/v1/admin/servers", json=payload, headers={"X-Admin-Api-Secret": admin_secret}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_lists_and_first_is_default(env) -> None:
    client, admin_secret, _ = env
    created = _create(client, admin_secret, "alpha")
    assert created["game_auth_secret"]
    assert created["is_default"] is True  # first server auto-defaults

    listed = client.get("/api/v1/admin/servers", headers={"X-Admin-Api-Secret": admin_secret})
    assert listed.status_code == 200
    assert any(s["slug"] == "alpha" for s in listed.json())


def test_duplicate_slug_conflicts(env) -> None:
    client, admin_secret, _ = env
    _create(client, admin_secret, "alpha")
    resp = client.post(
        "/api/v1/admin/servers",
        json={"slug": "alpha", "name": "dup", "host": "x"},
        headers={"X-Admin-Api-Secret": admin_secret},
    )
    assert resp.status_code == 409


def test_admin_auth_required(env) -> None:
    client, _admin_secret, _ = env
    resp = client.get("/api/v1/admin/servers")
    assert resp.status_code == 401


def test_public_list_only_visible(env) -> None:
    client, admin_secret, _ = env
    _create(client, admin_secret, "alpha")
    _create(client, admin_secret, "beta", is_visible=False)
    resp = client.get("/api/v1/servers")
    assert resp.status_code == 200
    slugs = {s["slug"] for s in resp.json()}
    assert "alpha" in slugs
    assert "beta" not in slugs
    # Public payload must not leak the secret.
    assert all("game_auth_secret" not in s for s in resp.json())


def test_secret_resolves_server(env) -> None:
    client, admin_secret, SessionLocal = env
    a = _create(client, admin_secret, "alpha")
    b = _create(client, admin_secret, "beta")
    assert a["game_auth_secret"] != b["game_auth_secret"]

    with SessionLocal() as session:
        resolved = require_game_server(session=session, x_game_auth_secret=b["game_auth_secret"])
        assert resolved.slug == "beta"


def test_cannot_delete_default(env) -> None:
    client, admin_secret, _ = env
    a = _create(client, admin_secret, "alpha")  # default
    resp = client.delete(
        f"/api/v1/admin/servers/{a['id']}", headers={"X-Admin-Api-Secret": admin_secret}
    )
    assert resp.status_code == 409
