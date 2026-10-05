"""Which of our builds suit a server, what it runs, and what is out of date.

Shared by the «Интеграция» page, the update notices (``core/integration_notices.py``) and the
admin banner. A build suits a server when it is meant for the server's core and Minecraft
version; withdrawn (yanked) builds are never offered.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import server_reports
from apps.api.app.core.releases import version_key
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.plugin_release import PluginRelease


def suits(release: PluginRelease, server: GameServer) -> bool:
    core = (server.server_core or "").lower()
    if core and release.platforms and core not in release.platforms:
        return False
    mc = (server.mc_version or "").strip()
    return not (mc and release.mc_versions and mc not in release.mc_versions)


def latest_for(releases: list[PluginRelease], server: GameServer, beta: bool = False) -> PluginRelease | None:
    """The build to offer: the newest recommended one that suits, else the newest that suits."""
    usable = [r for r in releases if not r.yanked and suits(r, server) and (beta or r.channel == "stable")]
    usable.sort(key=lambda r: version_key(r.version), reverse=True)
    return next((r for r in usable if r.recommended), usable[0] if usable else None)


def release_view(r: PluginRelease) -> dict[str, Any]:
    return {
        "id": str(r.id), "version": r.version, "platforms": r.platforms, "mc_versions": r.mc_versions,
        "changelog": r.changelog, "filename": r.filename, "size": r.size, "sha256": r.sha256,
        "recommended": r.recommended, "channel": r.channel, "important": r.important, "yanked": r.yanked,
        "source": r.source, "source_url": r.source_url,
        "published_at": r.published_at.isoformat() if r.published_at else None,
    }


def plugin_items(session: Session, server: GameServer, *, include_yanked: bool = False) -> list[dict[str, Any]]:
    """Catalog entries for this server with their builds, what it runs and whether that is old."""
    by_plugin = {r.plugin.lower(): r for r in server_reports.reports(session, server)}
    releases = session.scalars(select(PluginRelease).order_by(PluginRelease.published_at.desc())).all()

    items = []
    for e in cat.for_server(server):
        item = dict(e)
        item["has_config"] = e["key"] in cat.CONFIG_BUILDERS
        if e["kind"] == "ours":
            own = [r for r in releases if r.plugin == e["key"] and (include_yanked or not r.yanked)]
            own.sort(key=lambda r: version_key(r.version), reverse=True)
            latest = latest_for(own, server)
            item["releases"] = [release_view(r) for r in own]
            item["latest"] = release_view(latest) if latest else None
            rep = by_plugin.get(e["name"].lower())
            installed = rep.version if rep else None
            item["installed"] = {
                "version": installed,
                "reported_at": rep.reported_at.isoformat() if rep and rep.reported_at else None,
                "fresh": server_reports.is_fresh(rep) if rep else False,
                "modules": rep.modules if rep else {},
            } if rep else None
            item["outdated"] = bool(installed and latest and version_key(installed) < version_key(latest.version))
            # Changes between what the server runs and the build offered, newest first.
            item["changes_since_installed"] = [
                {"version": r.version, "changelog": r.changelog, "important": r.important}
                for r in own
                if installed and latest and r.channel == "stable"
                and version_key(installed) < version_key(r.version) <= version_key(latest.version)
            ] if item["outdated"] else []
        items.append(item)
    return items


def outdated(session: Session, server: GameServer) -> list[dict[str, Any]]:
    """Our plugins this server runs in an older version than the one offered."""
    return [
        {"key": i["key"], "name": i["name"], "installed": i["installed"]["version"], "latest": i["latest"]["version"],
         "important": any(c["important"] for c in i["changes_since_installed"])}
        for i in plugin_items(session, server) if i.get("outdated")
    ]
