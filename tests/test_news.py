from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import caller_permissions, get_current_staff_user
from apps.api.app.main import create_app
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.news import NewsPost

ALL_NEWS_PERMS = {
    "news.updates.view", "news.updates.manage",
    "news.media.view", "news.media.manage",
}


@pytest.fixture()
def env(tmp_path: Path):
    db_path = tmp_path / "news.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    GameServer.__table__.create(bind=engine)
    NewsPost.__table__.create(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with TestingSessionLocal() as session:
        server = GameServer(
            slug="alpha", name="Alpha", host="alpha.example.com",
            game_auth_secret="secret-alpha", is_default=True,
        )
        session.add(server)
        session.commit()
        server_id = str(server.id)

    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    # Staff identity + permissions are exercised by their own tests; here they
    # are stubbed so the news endpoints themselves are under test.
    perms = {"value": set(ALL_NEWS_PERMS)}
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[caller_permissions] = lambda: perms["value"]
    app.dependency_overrides[get_current_staff_user] = lambda: SimpleNamespace(site_login="admin")

    with TestClient(app) as client:
        yield client, server_id, perms

    app.dependency_overrides.clear()


def _create(client: TestClient, server_id: str, **overrides) -> dict:
    payload = {"title": "Патч 1.0", "body": "текст", "category": "update", **overrides}
    resp = client.post(f"/api/v1/admin/news?server_id={server_id}", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _patch(client: TestClient, server_id: str, post_id: str, body: dict) -> dict:
    resp = client.patch(f"/api/v1/admin/news/{post_id}?server_id={server_id}", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_cover_and_summary_can_be_cleared(env) -> None:
    """Regression: an explicit null used to be ignored, so a cover could never
    be removed once set."""
    client, server_id, _ = env
    post = _create(
        client, server_id,
        summary="краткое", cover_image_url="https://media.example.com/news/cover-1.webp",
    )
    assert post["cover_image_url"] and post["summary"]

    cleared = _patch(client, server_id, post["id"], {"summary": None, "cover_image_url": None})
    assert cleared["cover_image_url"] is None
    assert cleared["summary"] is None


def test_omitted_fields_stay_untouched(env) -> None:
    client, server_id, _ = env
    post = _create(client, server_id, summary="краткое", cover_image_url="https://x/y.webp")
    updated = _patch(client, server_id, post["id"], {"title": "Патч 1.1"})
    assert updated["title"] == "Патч 1.1"
    assert updated["summary"] == "краткое"
    assert updated["cover_image_url"] == "https://x/y.webp"


def test_category_move_requires_permission_on_target(env) -> None:
    client, server_id, perms = env
    post = _create(client, server_id, category="update")

    perms["value"] = {"news.updates.view", "news.updates.manage"}
    denied = client.patch(
        f"/api/v1/admin/news/{post['id']}?server_id={server_id}", json={"category": "media"}
    )
    assert denied.status_code == 403

    perms["value"] = set(ALL_NEWS_PERMS)
    moved = _patch(client, server_id, post["id"], {"category": "media"})
    assert moved["category"] == "media"


def test_scheduled_post_is_hidden_until_its_time(env) -> None:
    client, server_id, _ = env
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    post = _create(client, server_id, title="Скоро", is_published=True, published_at=future)
    assert post["is_scheduled"] is True

    # Admin sees it; the public feed does not.
    listed = client.get(f"/api/v1/admin/news?server_id={server_id}&category=update")
    assert "Скоро" in {p["title"] for p in listed.json()["items"]}

    public = client.get("/api/v1/news?server=alpha")
    assert public.status_code == 200
    assert public.json()["total"] == 0
    assert client.get(f"/api/v1/news/{post['slug']}?server=alpha").status_code == 404

    # Move it into the past → it goes live, no worker involved.
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    live = _patch(client, server_id, post["id"], {"published_at": past})
    assert live["is_scheduled"] is False
    assert client.get("/api/v1/news?server=alpha").json()["total"] == 1
    assert client.get(f"/api/v1/news/{post['slug']}?server=alpha").status_code == 200


def test_draft_broadcast_is_reported_not_swallowed(env) -> None:
    """Regression: a broadcast requested on a draft was silently dropped."""
    client, server_id, _ = env
    post = _create(client, server_id, is_published=False, post_telegram=True)
    bcast = post["broadcast"]
    assert bcast is not None
    assert bcast["telegram_ok"] is False
    assert "ерновик" in bcast["detail"]
    assert post["posted_telegram"] is False


def test_scheduled_create_does_not_broadcast_immediately(env) -> None:
    client, server_id, _ = env
    future = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    post = _create(
        client, server_id, is_published=True, published_at=future, post_discord=True
    )
    assert post["broadcast"]["discord_ok"] is False
    assert "тложенный" in post["broadcast"]["detail"]
    assert post["posted_discord"] is False


def test_admin_search_and_status_filter(env) -> None:
    client, server_id, _ = env
    _create(client, server_id, title="Патч про экономику", is_published=True)
    _create(client, server_id, title="Черновик про мобов", is_published=False)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    _create(client, server_id, title="Отложенный анонс", is_published=True, published_at=future)

    def titles(**params) -> set[str]:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        resp = client.get(f"/api/v1/admin/news?server_id={server_id}&category=update&{qs}")
        assert resp.status_code == 200, resp.text
        return {p["title"] for p in resp.json()["items"]}

    assert titles(q="мобов") == {"Черновик про мобов"}
    assert titles(status="draft") == {"Черновик про мобов"}
    assert titles(status="scheduled") == {"Отложенный анонс"}
    assert titles(status="published") == {"Патч про экономику"}


def test_pagination_reports_total(env) -> None:
    client, server_id, _ = env
    for i in range(5):
        _create(client, server_id, title=f"Пост {i}")
    resp = client.get(f"/api/v1/admin/news?server_id={server_id}&category=update&limit=2&offset=0")
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
