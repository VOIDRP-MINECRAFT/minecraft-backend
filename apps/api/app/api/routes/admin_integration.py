"""«Интеграция»: what an external server installs to join VoidRP, and whether it works.

For admins of partner servers (rights ``integration.view`` / ``integration.config``, per
server, part of server admin): the checklist from live plugin reports, our builds with their
versions and changes, ready configs with the server's secret (after the password), tips.
"""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.api.routes import integration_public
from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import (
    integration_history,
    integration_notices,
    integration_state,
    integration_updates,
    server_status,
)
from apps.api.app.core import server_reports
from apps.api.app.core.audit import record_audit
from apps.api.app.core.security import utc_now
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import (
    get_current_staff_user,
    require_admin_access,
    require_permission,
    require_reauth,
)
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.plugin_release import PluginRelease
from apps.api.app.models.user import User

router = APIRouter(prefix="/admin/integration", tags=["admin", "integration"],
                   dependencies=[Depends(require_permission("integration.view"))])

_Server = Annotated[GameServer, Depends(resolve_server)]
_Db = Annotated[Session, Depends(get_db_session)]


@router.get("")
def overview(server: _Server, session: _Db) -> dict:
    reports = server_reports.reports(session, server)
    have = server_reports.modules(session, server)
    items = integration_state.plugin_items(session, server)

    required = []
    for key, label in server_reports.REQUIRED_MODULES.items():
        state = have.get(key)
        required.append({"key": key, "label": label, "ok": state is not None,
                         "plugin": state and state["plugin"], "version": state and state["version"]})

    core_reported = next((r.core for r in reports if r.core and server_reports.is_fresh(r)), None)
    tips = []
    if server.is_external and server.rcon_port:
        egress = get_settings().backend_egress_ip
        if "console" in have:
            tips.append({"level": "warn", "text": "Консоль админки работает через VoidRpPerms — RCON больше не нужен. "
                         "Выключите его на сервере (enable-rcon=false в server.properties), а владелец сотрёт "
                         "RCON-порт и пароль в «Серверах»."})
        else:
            tips.append({"level": "warn", "text": "RCON открыт в интернет, а пароль к нему идёт открытым текстом. "
                         "Обновите VoidRpPerms до 0.5.0: консоль пойдёт через него, и RCON можно будет выключить. "
                         f"До тех пор закройте порт {server.rcon_port} фаерволом или разрешите его только для {egress}."})
    if not server.server_core:
        tips.append({"level": "warn", "text": "Не указано ядро сервера (Paper, Folia, NeoForge…) — "
                     "владелец задаёт его в «Серверах». От него зависит, какой способ входа ставить."})
    return {
        "server": {"slug": server.slug, "name": server.name, "is_external": server.is_external,
                   "item_bans_enabled": (server.features or {}).get("item_bans") is True,
                   "server_core": server.server_core, "core_label": cat.CORE_LABELS.get(server.server_core or ""),
                   "core_reported": core_reported, "auth_method": cat.auth_method(server),
                   "maintenance": server.maintenance, "is_visible": server.is_visible},
        "required": required,
        "missing_required": [r["label"] for r in required if not r["ok"]] if server.is_external else [],
        "items": items,
        "reports": [{"plugin": r.plugin, "version": r.version, "core": r.core, "modules": r.modules,
                     "reported_at": r.reported_at.isoformat(), "fresh": server_reports.is_fresh(r)} for r in reports],
        "tips": tips,
        "fresh_seconds": server_reports.FRESH_SECONDS,
        "doctor": integration_public.doctor_of(server),
        "inventory": integration_updates.analysis(server, items),
        "history": integration_history.recent(session, server),
        "status": server_status.summary(session, server),
        "incidents": server_status.incidents(session, server),
        "secret": {
            "previous_until": server.previous_secret_until.isoformat()
            if server.previous_secret_until and server.previous_secret_until > utc_now() else None,
            "old_secret_plugins": integration_updates.old_secret_plugins(server),
        },
        "settings": {"auto_update": bool((server.integration_settings or {}).get("auto_update")),
                     "beta": bool((server.integration_settings or {}).get("beta")),
                     "discord_webhook": (server.integration_settings or {}).get("discord_webhook"),
                     "public_status": public_status_on(server)},
        "scripts": {
            "update": f"curl -fsSL {get_settings().public_api_url.rstrip('/')}/api/v1/integration/voidrp-update.sh | bash",
            "doctor": f"curl -fsSL {get_settings().public_api_url.rstrip('/')}/api/v1/integration/voidrp-doctor.sh | bash",
        },
        "api_url": get_settings().public_api_url,
        "backend_egress_ip": get_settings().backend_egress_ip,
    }


@router.get("/releases/{release_id}/download")
def download_release(release_id: UUID, session: _Db) -> FileResponse:
    r = session.get(PluginRelease, release_id)
    if r is None or not os.path.isfile(r.storage_path):
        raise HTTPException(status_code=404, detail="Файл релиза не найден")
    base = os.path.realpath(cat.releases_dir())
    if not os.path.realpath(r.storage_path).startswith(base + os.sep):
        raise HTTPException(status_code=404, detail="Файл релиза не найден")
    return FileResponse(r.storage_path, filename=r.filename, media_type="application/java-archive")


@router.get("/config/{key}", dependencies=[Depends(require_permission("integration.config")), Depends(require_reauth)])
def download_config(key: str, server: _Server, session: _Db, request: Request,
                    actor: Annotated[User, Depends(get_current_staff_user)]) -> PlainTextResponse:
    builder = cat.CONFIG_BUILDERS.get(key)
    e = cat.entry(key)
    if builder is None or e is None:
        raise HTTPException(status_code=404, detail="Для этого плагина нет конфига")
    # The file carries the server's secret: every download goes to the audit log.
    record_audit(session, category="integration", action="config_download", actor=actor,
                 target_type="server", target_id=str(server.id), target_label=server.slug,
                 server_id=server.id, meta={"plugin": key}, request=request)
    filename = os.path.basename(e["config_path"])
    return PlainTextResponse(builder(server), headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── My Telegram notices ───────────────────────────────────────────────────────
class NotifyPrefs(BaseModel):
    releases: str = Field(default="all", pattern=r"^(all|important|none)$")
    beta: bool = False
    health: bool = True


@router.get("/notify")
def get_notify(actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    return {"prefs": integration_notices.prefs(actor), "telegram_linked": bool(actor.telegram_user_id),
            "telegram_username": actor.telegram_username,
            # Platform admins see every server: they get the admin banner, not a message per partner.
            "platform_admin": bool(actor.is_admin)}


@router.put("/notify")
def put_notify(payload: NotifyPrefs, session: _Db, actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    user = session.get(User, actor.id)
    user.integration_notify = payload.model_dump()
    session.commit()
    return {"prefs": integration_notices.prefs(user)}


# ── Releases (platform admins) ────────────────────────────────────────────────
class ReleasePatch(BaseModel):
    recommended: bool | None = None
    yanked: bool | None = None
    important: bool | None = None


@router.get("/releases", dependencies=[Depends(require_admin_access)])
def list_releases(session: _Db) -> dict:
    rows = session.scalars(select(PluginRelease).order_by(PluginRelease.published_at.desc())).all()
    by_plugin: dict[str, list[dict]] = {}
    for r in rows:
        by_plugin.setdefault(r.plugin, []).append(integration_state.release_view(r))
    plugins = [{"key": e["key"], "name": e["name"], "repo": e.get("repo"),
                "repo_url": f"https://github.com/{get_settings().github_org}/{e['repo']}" if e.get("repo") else None,
                "releases": by_plugin.get(e["key"], [])}
               for e in cat.CATALOG if e["kind"] == "ours"]
    from apps.api.app.core import support

    pol = support.policies(session)
    for p in plugins:
        row = pol.get(p["key"])
        p["min_supported"] = row.min_version if row else None
        p["support_note"] = row.note if row else None
    return {"plugins": plugins, "github_token": bool((get_settings().github_token or "").strip())}


class SupportPolicy(BaseModel):
    min_version: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=500)


@router.put("/support/{plugin}", dependencies=[Depends(require_admin_access)])
def put_support(plugin: str, payload: SupportPolicy, session: _Db, request: Request,
                actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    """The oldest supported version of a plugin; servers below it are told once to update."""
    from apps.api.app.core import support

    if cat.entry(plugin) is None:
        raise HTTPException(status_code=404, detail="Нет такого плагина")
    row = support.set_min(session, plugin, payload.min_version, payload.note, by=actor.site_login)
    record_audit(session, category="integration", action="support_policy", actor=actor,
                 target_type="plugin", target_id=plugin, target_label=plugin,
                 meta=payload.model_dump(), request=request)
    sent = integration_notices.announce_unsupported(session, plugin) if row.min_version else 0
    return {"plugin": plugin, "min_version": row.min_version, "note": row.note, "notified": sent}


@router.patch("/releases/{release_id}", dependencies=[Depends(require_admin_access)])
def patch_release(release_id: UUID, payload: ReleasePatch, session: _Db, request: Request,
                  actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    from apps.api.app.core import releases

    r = session.get(PluginRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Релиз не найден")
    if payload.yanked is not None:
        r.yanked = payload.yanked
        if r.yanked:
            r.recommended = False
    if payload.recommended is True:
        releases.recommend(session, r)
    elif payload.recommended is False:
        r.recommended = False
    if payload.important is not None:
        r.important = payload.important
    record_audit(session, category="integration", action="release_update", actor=actor,
                 target_type="plugin_release", target_id=str(r.id), target_label=f"{r.plugin} {r.version}",
                 meta=payload.model_dump(exclude_none=True), request=request)
    session.commit()
    return integration_state.release_view(r)


@router.post("/releases/sync", dependencies=[Depends(require_admin_access)])
def sync_releases() -> dict:
    """Takes new GitHub Releases now instead of waiting for the next cron run."""
    from apps.worker import release_sync

    added = release_sync.run()
    return {"added": [{"plugin": r.plugin, "version": r.version, "filename": r.filename} for r in added]}


@router.post("/install-token", dependencies=[Depends(require_permission("integration.config")), Depends(require_reauth)])
def install_token(server: _Server, session: _Db, request: Request,
                  actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    """A one-time install.sh link (15 min): it writes configs with the server's secret."""
    record_audit(session, category="integration", action="install_token", actor=actor,
                 target_type="server", target_id=str(server.id), target_label=server.slug,
                 server_id=server.id, request=request)
    return integration_public.issue_token(server, actor)


@router.get("/bundle.zip", dependencies=[Depends(require_permission("integration.config")), Depends(require_reauth)])
def bundle_zip(server: _Server, session: _Db, request: Request,
               actor: Annotated[User, Depends(get_current_staff_user)]) -> Response:
    """Everything in one archive, for hosts with only a web panel: unpack into the server folder."""
    import io
    import zipfile

    import httpx

    from apps.api.app.core import integration_scripts

    items = integration_state.plugin_items(session, server)
    ours = [i for i in items if i["kind"] == "ours" and not i.get("client_side") and i.get("latest")
            and (i.get("required") or i.get("installed"))]
    wanted = {n for i in ours for n in (i.get("needs") or [])}
    folder = "mods" if (server.server_core or "") in cat.MOD_CORES else "plugins"
    buf = io.BytesIO()
    readme = [f"VoidRP — файлы для сервера «{server.name}» ({server.slug}).", "",
              "Распакуйте архив в папку сервера (там, где server.properties), с заменой файлов,",
              "и перезапустите сервер. Если в plugins/ уже лежат старые версии этих плагинов",
              "под другими именами — удалите их, чтобы не было двух копий.", "",
              "Внутри конфиги с секретом сервера: не выкладывайте архив в открытый доступ.", "", "Состав:"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in ours:
            r = session.get(PluginRelease, UUID(i["latest"]["id"]))
            z.write(r.storage_path, f"{folder}/{r.filename}")
            readme.append(f"  {folder}/{r.filename} — {i['name']} {r.version}")
            if i.get("has_config"):
                z.writestr(i["config_path"], cat.CONFIG_BUILDERS[i["key"]](server))
                readme.append(f"  {i['config_path']}")
        for i in items:
            if i["kind"] != "third_party" or i["key"] not in wanted or not i.get("modrinth"):
                continue
            f = integration_scripts.modrinth_file(i["modrinth"], i.get("version"), server.mc_version)
            try:
                data = httpx.get(f["url"], timeout=60, follow_redirects=True).content if f else None
            except httpx.HTTPError:
                data = None
            if data:
                z.writestr(f"plugins/{f['filename']}", data)
                readme.append(f"  plugins/{f['filename']} — {i['name']} {f['version']} (Modrinth)")
            else:
                readme.append(f"  {i['name']}: скачайте сами — {i.get('url')}")
        z.writestr("VOIDRP-README.txt", "\n".join(readme) + "\n")
    record_audit(session, category="integration", action="bundle_download", actor=actor,
                 target_type="server", target_id=str(server.id), target_label=server.slug,
                 server_id=server.id, request=request)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="voidrp-{server.slug}.zip"'})


class IntegrationSettings(BaseModel):
    auto_update: bool = False
    beta: bool = False
    discord_webhook: str | None = Field(default=None, max_length=300)
    public_status: bool | None = None


@router.put("/settings", dependencies=[Depends(require_permission("integration.config"))])
def put_settings(payload: IntegrationSettings, server: _Server, session: _Db, request: Request,
                 actor: Annotated[User, Depends(get_current_staff_user)]) -> dict:
    """Auto-update of our plugins on this server (VoidRpPerms 0.6.0+ downloads them)."""
    from apps.api.app.core import integration_discord

    hook = (payload.discord_webhook or "").strip()
    if hook and not integration_discord.WEBHOOK.match(hook):
        raise HTTPException(status_code=422, detail="Это не адрес вебхука Discord (https://discord.com/api/webhooks/…)")
    srv = session.get(GameServer, server.id)
    data = payload.model_dump(exclude_none=True)
    data["discord_webhook"] = hook or None
    srv.integration_settings = {**(srv.integration_settings or {}), **data}
    record_audit(session, category="integration", action="settings", actor=actor,
                 target_type="server", target_id=str(srv.id), target_label=srv.slug,
                 server_id=srv.id, meta=payload.model_dump(), request=request)
    return {"settings": srv.integration_settings}


@router.post("/selftest")
def selftest(server: _Server, session: _Db) -> dict:
    """«Проверить связь»: VoidRpPerms answers /voidrp status through the console queue."""
    from apps.api.app.core import server_console

    if not server_console.has_module(session, server, "console"):
        raise HTTPException(status_code=409, detail="Нужен VoidRpPerms 0.6.0+ с модулем консоли — он отвечает на проверку")
    try:
        return {"output": server_console.run(server, "voidrp status", timeout=10)}
    except server_console.PluginConsoleError as exc:
        raise HTTPException(status_code=504, detail=str(exc))


def public_status_on(server: GameServer) -> bool:
    """The public status page and badge: on by default for a listed server, by the owner's switch."""
    value = (server.integration_settings or {}).get("public_status")
    return bool(value) if value is not None else bool(server.is_visible and not server.staff_only)


@router.post("/discord-test", dependencies=[Depends(require_permission("integration.config"))])
def discord_test(server: _Server, payload: IntegrationSettings) -> dict:
    """Sends a test message to the webhook typed in (not saved yet)."""
    from apps.api.app.core import integration_discord

    hook = (payload.discord_webhook or "").strip()
    if not integration_discord.WEBHOOK.match(hook):
        raise HTTPException(status_code=422, detail="Это не адрес вебхука Discord (https://discord.com/api/webhooks/…)")
    if not integration_discord.test(server, hook):
        raise HTTPException(status_code=502, detail="Discord не принял сообщение — проверьте, что вебхук не удалён")
    return {"ok": True}
