"""Recording a build of our plugins and mods for the «Интеграция» page.

Shared by the manual publisher (``apps.worker.publish_release``) and the GitHub sync
(``apps.worker.release_sync``): the jar goes under ``RELEASES_DIR/<plugin>/<version>/``, its
size and sha256 are kept, and a stable build becomes the recommended one for its Minecraft
versions (the previous recommended build for the same versions steps down).
"""
from __future__ import annotations

import hashlib
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import integration_catalog as cat
from apps.api.app.models.plugin_release import PluginRelease


def version_key(v: str | None) -> tuple:
    """Orders 1.10.0 after 1.9.0, and 1.4.0-beta.1 before 1.4.0."""
    main, _, pre = (v or "").partition("-")
    if not main.strip():
        return ((-1,),)  # no version at all sorts before every real one
    parts: list[tuple] = []
    for p in main.split("."):
        if not p:
            continue  # "" / None: no version at all sorts first, not after every number
        parts.append((0, int(p)) if p.isdigit() else (1, p))
    # A release sorts after any of its pre-releases.
    parts.append((1,) if not pre else (0, pre))
    return tuple(parts)


def record(
    session: Session,
    *,
    plugin: str,
    version: str,
    data: bytes,
    filename: str,
    platforms: list[str],
    mc_versions: list[str],
    changelog: str | None,
    channel: str = "stable",
    recommended: bool,
    published_by: str | None,
    source: str = "manual",
    github_asset_id: int | None = None,
    source_url: str | None = None,
) -> PluginRelease:
    """Stores the file and upserts its row (by plugin + version + filename). Commits nothing."""
    target_dir = os.path.join(cat.releases_dir(), plugin, version)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, filename)
    tmp = target + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)

    row = session.scalar(select(PluginRelease).where(
        PluginRelease.plugin == plugin, PluginRelease.version == version, PluginRelease.filename == filename))
    if row is None:
        row = PluginRelease(plugin=plugin, version=version, filename=filename)
        session.add(row)
    row.platforms = platforms
    row.mc_versions = mc_versions
    row.changelog = changelog or None
    row.storage_path = target
    row.size = len(data)
    row.sha256 = hashlib.sha256(data).hexdigest()
    row.published_by = published_by
    row.channel = channel
    row.source = source
    row.github_asset_id = github_asset_id
    row.source_url = source_url
    if recommended:
        recommend(session, row)
    return row


def recommend(session: Session, row: PluginRelease) -> None:
    """Makes ``row`` the build offered first for its Minecraft versions."""
    for other in session.scalars(select(PluginRelease).where(
            PluginRelease.plugin == row.plugin, PluginRelease.recommended.is_(True))).all():
        if other is not row and set(other.mc_versions or []) & set(row.mc_versions or []):
            other.recommended = False
    row.recommended = True
    row.yanked = False
