"""The oldest version of each of our plugins we still support.

Set by a platform admin on the «Релизы» tab (or by ``min_supported`` in a release's
release.json). A server below it gets a red mark on its «Интеграция» page and, once per policy,
a Telegram message to the people running it (``core/integration_notices.announce_unsupported``).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.releases import version_key
from apps.api.app.models.plugin_support import PluginSupport


def policies(session: Session) -> dict[str, PluginSupport]:
    return {p.plugin: p for p in session.scalars(select(PluginSupport)).all()}


def set_min(session: Session, plugin: str, min_version: str | None, note: str | None = None,
            by: str | None = None) -> PluginSupport:
    """Sets (or clears, with None) the policy. Commits nothing."""
    row = session.get(PluginSupport, plugin)
    if row is None:
        row = PluginSupport(plugin=plugin)
        session.add(row)
    row.min_version = (min_version or "").strip() or None
    if note is not None:
        row.note = note.strip() or None
    row.updated_by = by
    return row


def below(installed: str | None, policy: PluginSupport | None) -> bool:
    return bool(installed and policy and policy.min_version
                and version_key(installed) < version_key(policy.min_version))
