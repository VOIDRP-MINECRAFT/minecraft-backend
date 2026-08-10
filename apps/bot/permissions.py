from __future__ import annotations

from apps.api.app.core.permissions import resolve_user_permissions
from apps.api.app.models.user import User


def perms_for(user: User | None) -> set[str]:
    """Effective permission set for a linked user (empty if not linked/staff)."""
    return resolve_user_permissions(user)


def can_publish_any_news(perms: set[str]) -> bool:
    return "news.updates.manage" in perms or "news.media.manage" in perms


def can_manage_games(perms: set[str]) -> bool:
    return "telegram.games.manage" in perms
