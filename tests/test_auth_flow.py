from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.db import get_db_session
from apps.api.app.main import create_app
from apps.api.app.models.base import Base


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_register_login_refresh_logout_flow(client: TestClient) -> None:
    register_payload = {
        "site_login": "Yann",
        "minecraft_nickname": "YannGotti",
        "email": "yann@example.com",
        "password": "StrongPassword123!",
        "password_repeat": "StrongPassword123!",
    }
    register_response = client.post("/api/v1/auth/register", json=register_payload)
    assert register_response.status_code == 201, register_response.text
    body = register_response.json()
    assert body["user"]["site_login"] == "Yann"
    assert body["player_account"]["minecraft_nickname"] == "YannGotti"

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "login": "YANn",
            "password": "StrongPassword123!",
            "device_name": "pytest",
        },
    )
    assert login_response.status_code == 200, login_response.text
    login_body = login_response.json()
    assert login_body["token_type"] == "bearer"
    assert login_body["access_token"]
    assert login_body["refresh_token"]

    access_token = login_body["access_token"]
    refresh_token = login_body["refresh_token"]

    me_response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 200, me_response.text
    me_body = me_response.json()
    assert me_body["user"]["email"] == "yann@example.com"

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token, "device_name": "pytest-rotated"},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    refreshed_body = refresh_response.json()
    assert refreshed_body["refresh_token"] != refresh_token

    logout_response = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refreshed_body["refresh_token"]},
    )
    assert logout_response.status_code == 204, logout_response.text

    invalid_refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refreshed_body["refresh_token"], "device_name": "pytest-rotated"},
    )
    assert invalid_refresh_response.status_code == 401
