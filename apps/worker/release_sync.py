"""Take new GitHub Releases of our plugins and mods into the «Интеграция» page.

    .venv/bin/python -m apps.worker.release_sync            # every catalog repo (cron, every 10 min)
    .venv/bin/python -m apps.worker.release_sync voidrp-auth # one plugin, right after a release

A tag ``v1.4.0`` in one of our repositories makes CI build the jar and publish a GitHub
Release whose text is the tag's message. This worker downloads its jars, records them as
``plugin_releases`` (``core/releases.py``) and announces the new build to the servers it
concerns. A pre-release (``v1.5.0-beta.1``) goes in as the beta channel and is never
recommended on its own. Releases already taken (by asset id) are skipped, so a run that
finds nothing new costs one API call per repository.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys

import httpx
from sqlalchemy import select

from apps.api.app.config import get_settings
from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import releases
from apps.api.app.db import SessionLocal
from apps.api.app.models.plugin_release import PluginRelease

log = logging.getLogger("release_sync")

API = "https://api.github.com"
# Not the jar a server installs: sources, docs, the unshaded jar next to a shadow "-all" one.
_SKIP = re.compile(r"-(sources|javadoc|plain|dev)\.jar$", re.IGNORECASE)
_MC = re.compile(r"\+mc([0-9][0-9.]*)\.jar$", re.IGNORECASE)


class GitHub:
    """Reads releases and downloads their files.

    With ``GITHUB_TOKEN`` set it talks to the API itself. Without one it goes through the
    GitHub CLI when that is signed in on this machine (it is: pushes go through it), which
    also reaches the private repositories; failing both, anonymously (public repos only).
    """

    def __init__(self) -> None:
        self.token = (get_settings().github_token or "").strip()
        # cron runs with a bare PATH; the CLI is installed per user.
        search = os.pathsep.join([os.environ.get("PATH", ""), os.path.expanduser("~/.local/bin"), "/usr/local/bin"])
        self.gh = shutil.which("gh", path=search) if not self.token else None
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "VoidRP-release-sync",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        # httpx drops Authorization on the redirect to GitHub's file storage (another host).
        self.http = httpx.Client(headers=headers, timeout=60.0, follow_redirects=True)

    def releases(self, repo: str) -> list[dict] | None:
        """The repository's latest releases, or None when it is not found (or not visible)."""
        path = f"repos/{get_settings().github_org}/{repo}/releases?per_page=20"
        if self.gh:
            res = subprocess.run([self.gh, "api", path], capture_output=True, timeout=60)
            if res.returncode == 0:
                return json.loads(res.stdout)
            if b"Not Found" in res.stderr:
                return None
            raise httpx.HTTPError(res.stderr.decode(errors="replace").strip()[:300])
        resp = self.http.get(f"{API}/{path}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def download(self, asset: dict) -> bytes:
        if self.gh:
            res = subprocess.run([self.gh, "api", "-H", "Accept: application/octet-stream", asset["url"]],
                                 capture_output=True, timeout=300)
            if res.returncode != 0:
                raise httpx.HTTPError(res.stderr.decode(errors="replace").strip()[:300])
            return res.stdout
        resp = self.http.get(asset["url"], headers={"Accept": "application/octet-stream"})
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self.http.close()


def _jars(release: dict) -> list[dict]:
    jars = [a for a in release.get("assets") or [] if a["name"].lower().endswith(".jar") and not _SKIP.search(a["name"])]
    shadow = [a for a in jars if a["name"].lower().endswith("-all.jar")]
    return shadow or jars


def _targets(entry: dict, asset_name: str) -> tuple[list[str], list[str]]:
    """Platforms and Minecraft versions of one jar, from its name or the catalog's defaults."""
    rules = entry.get("release") or {}
    m = _MC.search(asset_name)
    if m:
        mc = m.group(1).rstrip(".")
        return list((rules.get("by_mc") or {}).get(mc) or rules.get("platforms") or entry["cores"]), [mc]
    return list(rules.get("platforms") or entry["cores"]), list(rules.get("mc") or [])


def sync_plugin(gh: GitHub, entry: dict) -> list[PluginRelease]:
    """New builds of one plugin; committed. Returns the rows that were added."""
    found = gh.releases(entry["repo"])
    if found is None:
        log.warning("%s: repository %s not found (private, and neither GITHUB_TOKEN nor gh?)", entry["key"], entry["repo"])
        return []

    added: list[PluginRelease] = []
    with SessionLocal() as session:
        known = set(session.scalars(select(PluginRelease.github_asset_id).where(
            PluginRelease.plugin == entry["key"], PluginRelease.github_asset_id.is_not(None))).all())
        # Oldest first, so the newest stable build ends up the recommended one.
        for rel in sorted(found, key=lambda r: r.get("published_at") or ""):
            if rel.get("draft"):
                continue
            jars = [a for a in _jars(rel) if a["id"] not in known]
            if not jars:
                continue
            version = (rel.get("tag_name") or "").removeprefix("v")
            # scripts/release_plugin.sh --important puts this marker first in the tag's message.
            body = (rel.get("body") or "").strip()
            important = body.lower().startswith("[important]")
            if important:
                body = body[len("[important]"):].strip()
            beta = bool(rel.get("prerelease")) or "-" in version
            several = len(_jars(rel)) > 1
            for asset in jars:
                data = gh.download(asset)
                if len(data) != asset.get("size", len(data)):
                    log.warning("%s %s: %s came short, skipped", entry["key"], version, asset["name"])
                    continue
                platforms, mc = _targets(entry, asset["name"])
                # One jar per Minecraft version keeps its own name; a single jar is saved under
                # the name the server installs it as.
                filename = asset["name"] if several else entry["install_as"].rsplit("/", 1)[-1]
                row = releases.record(
                    session, plugin=entry["key"], version=version, data=data, filename=filename,
                    platforms=platforms, mc_versions=mc, changelog=body,
                    channel="beta" if beta else "stable", recommended=not beta,
                    published_by=(rel.get("author") or {}).get("login"), source="github",
                    github_asset_id=asset["id"], source_url=rel.get("html_url"),
                )
                row.important = important
                session.flush()
                added.append(row)
                log.info("%s %s: %s (%s, MC %s, %s)", entry["key"], version, filename,
                         ",".join(platforms), ",".join(mc), "beta" if beta else "stable")
        session.commit()
        for row in added:
            session.refresh(row)
            session.expunge(row)
    return added


def run(only: str | None = None) -> list[PluginRelease]:
    entries = [e for e in cat.CATALOG if e.get("kind") == "ours" and e.get("repo") and (only is None or e["key"] == only)]
    added: list[PluginRelease] = []
    gh = GitHub()
    try:
        for entry in entries:
            try:
                added += sync_plugin(gh, entry)
            except (httpx.HTTPError, subprocess.SubprocessError, ValueError) as exc:
                log.warning("%s: GitHub did not answer: %s", entry["key"], exc)
    finally:
        gh.close()
    if added:
        from apps.api.app.core import integration_notices

        integration_notices.announce_releases(added)
    return added


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only and cat.entry(only) is None:
        print(f"unknown plugin key: {only}", file=sys.stderr)
        return 2
    added = run(only)
    print(f"new builds: {len(added)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
