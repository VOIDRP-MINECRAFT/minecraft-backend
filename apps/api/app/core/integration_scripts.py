"""Shell scripts that connect an external server to VoidRP, and what they download.

* ``install.sh`` — one command from the «Интеграция» page, by a one-time token (15 min): puts
  our plugins (and the third-party ones they need, from Modrinth) and the configs with the
  server's secret in place, backing up what it replaces.
* ``voidrp-update.sh`` — takes newer builds of what the server already runs; authenticates
  with the secret from the plugin's own config, so it can run from the partner's cron.
* ``voidrp-doctor.sh`` — checks Java, DNS, HTTPS to the API, clock, an open RCON port,
  versions and plugins known to clash, and prints a report to paste (``--send`` puts it on
  the page).

The scripts read a line-based list rather than JSON, so they need nothing beyond bash, curl,
coreutils and unzip:

    SERVER <slug> <core> <mc> <java>
    FILE <plugin|mod> <required|optional> <match name> <sha256:…|sha512:…> <filename> <url>
    CONFIG <path> <url>
    NOTE <text>
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.core import integration_catalog as cat
from apps.api.app.core import integration_state
from apps.api.app.models.game_server import GameServer
from apps.api.app.services.redis_cache_service import RedisCacheService

log = logging.getLogger(__name__)

# Clients the server's Minecraft version needs, for the Java check.
def java_for(mc: str | None) -> int:
    mc = (mc or "").strip()
    if not mc:
        return 21
    major = mc.split(".")[0]
    return 25 if major.isdigit() and int(major) >= 26 else 21


def _api() -> str:
    return get_settings().public_api_url.rstrip("/") + "/api/v1"


# ── Third-party plugins from Modrinth ─────────────────────────────────────────
def modrinth_file(project: str, version: str | None, mc: str | None, loader: str = "paper") -> dict | None:
    """The tested version if Modrinth has it for this Minecraft, else the newest one that fits."""
    key = f"modrinth_file:{project}:{version}:{mc}:{loader}"
    cache = RedisCacheService()
    cached = cache.get_json(key)
    if cached is not None:
        return cached or None
    params: dict[str, str] = {"loaders": f'["{loader}"]'}
    if mc:
        params["game_versions"] = f'["{mc}"]'
    found: dict | None = None
    try:
        resp = httpx.get(f"https://api.modrinth.com/v2/project/{project}/version", params=params,
                         headers={"User-Agent": "VoidRP-integration (+https://void-rp.ru)"}, timeout=15)
        versions = resp.json() if resp.status_code == 200 else []
        pick = next((v for v in versions if version and version in v.get("version_number", "")), versions[0] if versions else None)
        if pick:
            f = next((x for x in pick["files"] if x.get("primary")), pick["files"][0])
            found = {"url": f["url"], "filename": f["filename"], "sha512": f["hashes"].get("sha512"),
                     "version": pick["version_number"]}
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        log.warning("Modrinth %s: %s", project, exc)
    cache.set_json(key, found or {}, ttl_seconds=6 * 3600 if found else 600)
    return found


# ── What a server gets ────────────────────────────────────────────────────────
def bundle(session: Session, server: GameServer, file_url: Callable[[str], str],
           config_url: Callable[[str], str] | None, *, include_optional: bool) -> str:
    """The list the scripts read. ``file_url(release_id)`` / ``config_url(key)`` build the links
    (by install token or for the secret); without ``config_url`` no configs are listed."""
    core = (server.server_core or "").lower()
    lines = [f"SERVER {server.slug} {core or '-'} {server.mc_version or '-'} {java_for(server.mc_version)}"]
    items = integration_state.plugin_items(session, server)
    wanted: set[str] = set()
    for it in items:
        if it["kind"] != "ours" or it.get("client_side"):
            continue
        if not (it.get("required") or include_optional or it.get("installed")):
            continue
        latest = it.get("latest")
        if not latest:
            lines.append(f"NOTE Для {it['name']} пока нет сборки под это ядро и версию Minecraft.")
            continue
        kind = "mod" if core in cat.MOD_CORES else "plugin"
        match = it["install_as"].rsplit("/", 1)[-1].removesuffix(".jar") if kind == "mod" else (it.get("plugin_name") or it["name"])
        lines.append(f"FILE {kind} {'required' if it.get('required') else 'optional'} {match} "
                     f"sha256:{latest['sha256']} {latest['filename']} {file_url(latest['id'])}")
        wanted.update(it.get("needs") or [])
        if config_url and it.get("has_config"):
            lines.append(f"CONFIG {it['config_path']} {config_url(it['key'])}")
    for it in items:
        if it["kind"] != "third_party" or it["key"] not in wanted or not it.get("modrinth"):
            continue
        f = modrinth_file(it["modrinth"], it.get("version"), server.mc_version)
        if not f or not f.get("sha512"):
            lines.append(f"NOTE {it['name']} поставьте вручную: {it.get('url')}")
            continue
        lines.append(f"FILE plugin required {it.get('plugin_name') or it['name']} sha512:{f['sha512']} {f['filename']} {f['url']}")
    return "\n".join(lines) + "\n"


# ── The scripts ───────────────────────────────────────────────────────────────
_COMMON = r'''
set -euo pipefail
API="__API__"
c_ok() { printf '\033[32m✔\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_err() { printf '\033[31m✘\033[0m %s\n' "$*" >&2; }
need() { command -v "$1" >/dev/null 2>&1 || { c_err "нужна программа $1"; exit 1; }; }

# The server folder: the argument, or the current one; it holds server.properties.
server_dir() {
  local d="${1:-$PWD}"
  [ -f "$d/server.properties" ] || { c_err "в $d нет server.properties — запустите из папки сервера или передайте её путь"; exit 1; }
  (cd "$d" && pwd)
}

# Is a java process running out of this folder?
server_running() {
  local p
  for p in $(pgrep -x java 2>/dev/null; pgrep -f 'java.*\.jar' 2>/dev/null); do
    [ "$(readlink "/proc/$p/cwd" 2>/dev/null)" = "$DIR" ] && return 0
  done
  return 1
}

# The jar in plugins/ whose plugin.yml has this name, or a mod in mods/ starting with it.
existing_jar() {
  local kind="$1" name="$2" j n
  if [ "$kind" = mod ]; then
    for j in "$DIR"/mods/"$name"*.jar; do [ -f "$j" ] && { echo "$j"; return; }; done
    return
  fi
  for j in "$DIR"/plugins/*.jar; do
    [ -f "$j" ] || continue
    n="$(unzip -p "$j" plugin.yml paper-plugin.yml 2>/dev/null | grep -m1 -E '^name:' | sed -E "s/^name:[[:space:]]*['\"]?([^'\" ]+).*/\1/" || true)"
    [ "$n" = "$name" ] && { echo "$j"; return; }
  done
}

hash_ok() {
  local file="$1" want="$2"
  case "$want" in
    sha256:*) [ "$(sha256sum "$file" | cut -d' ' -f1)" = "${want#sha256:}" ] ;;
    sha512:*) [ "$(sha512sum "$file" | cut -d' ' -f1)" = "${want#sha512:}" ] ;;
    *) return 1 ;;
  esac
}

# --dry-run: says what would change, touches nothing.
dry_check() {
  local kind="$1" name="$2" want="$3" filename="$4" old
  old="$(existing_jar "$kind" "$name")"
  if [ -n "$old" ] && hash_ok "$old" "$want"; then c_ok "$name: актуален"
  else c_warn "$name: поставлю $filename${old:+ вместо $(basename "$old")}"; fi
}

# The server's secret from the config of one of our plugins (for the scripts that need no link).
find_secret() {
  local f v
  for f in plugins/VoidRpPerms/config.yml plugins/VoidRpAuth/config.yml plugins/VoidRpGuard/config.yml config/voidrp-auth-bridge.properties; do
    [ -f "$DIR/$f" ] || continue
    v="$(grep -m1 -E '^\s*(secret|game-auth-secret|gameSecret)\s*[:=]' "$DIR/$f" | sed -E "s/^[^:=]*[:=][[:space:]]*['\"]?([^'\" ]+).*/\1/")"
    [ -n "$v" ] && { echo "$v"; return; }
  done
}

BACKUP=""
backup() {
  [ -e "$1" ] || return 0
  [ -n "$BACKUP" ] || { BACKUP="$DIR/voidrp-backup/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$BACKUP"; }
  mkdir -p "$BACKUP/$(dirname "${1#$DIR/}")"
  cp -a "$1" "$BACKUP/${1#$DIR/}"
}

# Puts one jar in place. On a running Paper server it goes to plugins/update/ under the old
# name (Paper swaps it at the next start); a mod waits for a stopped server.
CHANGED=0; WAITING=0
place_jar() {
  local kind="$1" level="$2" name="$3" want="$4" filename="$5" url="$6" tmp old dest
  tmp="$(mktemp)"
  # The server's secret goes to our API only, never to a third-party download (Modrinth).
  local auth=()
  case "$url" in "$API"/*) [ -n "${AUTH_HEADER:-}" ] && auth=(-H "$AUTH_HEADER") ;; esac
  if ! curl -fsSL ${auth[@]+"${auth[@]}"} -o "$tmp" "$url"; then c_err "$name: не скачался"; rm -f "$tmp"; return 1; fi
  if ! hash_ok "$tmp" "$want"; then c_err "$name: контрольная сумма не совпала, файл не поставлен"; rm -f "$tmp"; return 1; fi
  old="$(existing_jar "$kind" "$name")"
  if [ -n "$old" ] && hash_ok "$old" "$want"; then c_ok "$name: уже актуален ($(basename "$old"))"; rm -f "$tmp"; return 0; fi
  if [ "$kind" = plugin ] && [ "$RUNNING" = 1 ]; then
    mkdir -p "$DIR/plugins/update"
    dest="$DIR/plugins/update/$(basename "${old:-$filename}")"
    mv "$tmp" "$dest"; chmod 644 "$dest"
    c_ok "$name: $(basename "$dest") ждёт перезапуска в plugins/update/"
    WAITING=1; CHANGED=1; return 0
  fi
  if [ "$kind" = mod ] && [ "$RUNNING" = 1 ]; then
    c_warn "$name: сервер запущен — мод поставлю, когда он будет остановлен (запустите скрипт ещё раз)"
    rm -f "$tmp"; return 0
  fi
  [ -n "$old" ] && { backup "$old"; rm -f "$old"; }
  dest="$DIR/$([ "$kind" = mod ] && echo mods || echo plugins)/$filename"
  mkdir -p "$(dirname "$dest")"; mv "$tmp" "$dest"; chmod 644 "$dest"
  c_ok "$name: $filename${old:+ (было $(basename "$old"))}"
  CHANGED=1
}
'''

INSTALL = r'''#!/usr/bin/env bash
# VoidRP: подключение сервера «__NAME__» (__SLUG__). Сгенерировано в «Интеграции»,
# ссылка одноразовая и действует 15 минут. Запускать из папки сервера:
#   curl -fsSL __API__/i/__TOKEN__ | bash -s -- [папка сервера] [--all] [--dry-run]
# --all — поставить и необязательные плагины (античит VoidRpGuard с GrimAC и CoreProtect).
# --dry-run — только показать, что будет сделано (ссылка при этом остаётся рабочей 15 минут).
''' + _COMMON + r'''
ARGS=(); ALL=0; DRY=0
for a in "$@"; do case "$a" in --all) ALL=1 ;; --dry-run) DRY=1 ;; *) ARGS+=("$a") ;; esac; done
DIR="$(server_dir "${ARGS[0]:-}")"
need curl; need sha256sum; need sha512sum; need unzip
echo "── Подключение к VoidRP: $DIR"

BUNDLE="$(curl -fsSL "$API/i/__TOKEN__/bundle?all=$ALL")" || { c_err "ссылка устарела или уже не действует — возьмите новую в «Интеграции»"; exit 1; }
read -r _ SLUG CORE MC JAVA_NEED <<<"$(grep '^SERVER ' <<<"$BUNDLE")"

# Java
if command -v java >/dev/null 2>&1; then
  JV="$(java -version 2>&1 | head -1 | sed -E 's/.*version "([0-9]+).*/\1/')"
  if [ "${JV:-0}" -lt "$JAVA_NEED" ] 2>/dev/null; then c_warn "Java $JV, а Minecraft $MC нужна Java $JAVA_NEED+"; else c_ok "Java $JV"; fi
else c_warn "java не найдена в PATH — проверьте версию сами (нужна $JAVA_NEED+)"; fi

# Ядро
if [ -d "$DIR/plugins" ] && [ "$CORE" != neoforge ]; then c_ok "ядро: $CORE";
elif [ -d "$DIR/mods" ]; then c_ok "ядро: $CORE (папка mods)";
else c_warn "не вижу ни plugins/, ни mods/ — сервер запускался хоть раз?"; mkdir -p "$DIR/plugins"; fi

curl -fsS -o /dev/null --max-time 10 "$API/servers" && c_ok "связь с $API есть" || c_warn "сервер не достучался до $API — откройте исходящий 443"

RUNNING=0; server_running && RUNNING=1
[ "$RUNNING" = 1 ] && c_warn "сервер запущен: плагины встанут при перезапуске (через plugins/update/)"

if [ "$DRY" = 1 ]; then
  echo "── Пробный прогон: ничего не меняю"
  while read -r tag kind level name want filename url; do
    [ "$tag" = FILE ] && dry_check "$kind" "$name" "$want" "$filename"
  done <<<"$BUNDLE"
  while read -r tag path url; do
    [ "$tag" = CONFIG ] && c_warn "конфиг $path: $([ -f "$DIR/$path" ] && echo "заменю (старый — в voidrp-backup/)" || echo "создам")"
  done <<<"$BUNDLE"
  grep '^NOTE ' <<<"$BUNDLE" | cut -d' ' -f2- | while read -r n; do c_warn "$n"; done || true
  echo "Запустите без --dry-run, чтобы поставить."
  exit 0
fi

while read -r tag kind level name want filename url; do
  [ "$tag" = FILE ] || continue
  place_jar "$kind" "$level" "$name" "$want" "$filename" "$url" || true
done <<<"$BUNDLE"

while read -r tag path url; do
  [ "$tag" = CONFIG ] || continue
  tmp="$(mktemp)"
  if curl -fsSL -o "$tmp" "$url"; then
    if [ -f "$DIR/$path" ] && cmp -s "$tmp" "$DIR/$path"; then rm -f "$tmp"; continue; fi
    backup "$DIR/$path"; mkdir -p "$(dirname "$DIR/$path")"; mv "$tmp" "$DIR/$path"; chmod 600 "$DIR/$path"
    c_ok "конфиг $path (с секретом сервера)"; CHANGED=1
  else rm -f "$tmp"; c_err "конфиг $path не скачался"; fi
done <<<"$BUNDLE"

grep '^NOTE ' <<<"$BUNDLE" | cut -d' ' -f2- | while read -r n; do c_warn "$n"; done || true
[ -n "$BACKUP" ] && echo "Старые файлы — в ${BACKUP#$DIR/}"
if [ "$CHANGED" = 1 ]; then
  echo; echo "Готово. Перезапустите сервер — меньше чем через минуту в «Интеграции» загорятся «Вход» и «Мониторинг»."
  echo "Обновлять дальше: curl -fsSL $API/integration/voidrp-update.sh | bash"
else echo "Всё уже стоит."; fi
'''

UPDATE = r'''#!/usr/bin/env bash
# VoidRP: обновление наших плагинов на сервере. Берёт секрет сервера из конфига плагина,
# поэтому ссылка не нужна:
#   curl -fsSL __API__/integration/voidrp-update.sh | bash -s -- [папка сервера] [флаги]
#   --dry-run        показать, что обновится, ничего не меняя
#   --install-cron   обновлять каждую ночь в 05:17 (по времени сервера), лог — logs/voidrp-update.log
#   --remove-cron    убрать ночное обновление
#   --uninstall      снять плагины VoidRP (в voidrp-backup/), конфиги оставить; с --purge — и конфиги
# На работающем Paper новые jar ложатся в plugins/update/ (подменятся при перезапуске),
# моды — только при остановленном сервере. Конфиги не трогает.
''' + _COMMON + r'''
ARGS=(); DRY=0; CRON=""; UNINSTALL=0; PURGE=0
for a in "$@"; do case "$a" in
  --dry-run) DRY=1 ;; --install-cron) CRON=add ;; --remove-cron) CRON=remove ;;
  --uninstall) UNINSTALL=1 ;; --purge) PURGE=1 ;; *) ARGS+=("$a") ;;
esac; done
DIR="$(server_dir "${ARGS[0]:-}")"

if [ -n "$CRON" ]; then
  need crontab
  MARK="# voidrp-update $DIR"
  CUR="$(crontab -l 2>/dev/null | grep -vF "$MARK" || true)"
  if [ "$CRON" = add ]; then
    mkdir -p "$DIR/logs"
    LINE="17 5 * * * curl -fsSL $API/integration/voidrp-update.sh | bash -s -- '$DIR' >> '$DIR/logs/voidrp-update.log' 2>&1 $MARK"
    printf '%s\n%s\n' "$CUR" "$LINE" | sed '/^$/d' | crontab -
    c_ok "ночное обновление включено: каждый день в 05:17, лог — logs/voidrp-update.log"
    c_ok "новые версии встанут при ближайшем перезапуске сервера"
  else
    printf '%s\n' "$CUR" | sed '/^$/d' | crontab -
    c_ok "ночное обновление убрано"
  fi
  exit 0
fi

if [ "$UNINSTALL" = 1 ]; then
  RUNNING=0; server_running && RUNNING=1
  [ "$RUNNING" = 1 ] && { c_err "сервер запущен — остановите его, потом снимайте плагины"; exit 1; }
  for n in VoidRpPerms VoidRpAuth VoidRpGuard VoidRpGameSync; do
    j="$(existing_jar plugin "$n")"
    [ -n "$j" ] && { backup "$j"; rm -f "$j"; c_ok "$n снят ($(basename "$j"))"; }
    [ -f "$DIR/plugins/update/$(basename "${j:-none}")" ] && rm -f "$DIR/plugins/update/$(basename "$j")"
    if [ "$PURGE" = 1 ] && [ -d "$DIR/plugins/$n" ]; then backup "$DIR/plugins/$n"; rm -rf "$DIR/plugins/$n"; c_ok "папка plugins/$n убрана"; fi
  done
  for j in "$DIR"/mods/voidrp_auth_bridge*.jar; do [ -f "$j" ] && { backup "$j"; rm -f "$j"; c_ok "мод $(basename "$j") снят"; }; done
  [ -n "$BACKUP" ] && echo "Всё снятое — в ${BACKUP#$DIR/}; вернуть можно, скопировав обратно." || echo "Плагинов VoidRP не нашёл."
  echo "Не забудьте вернуть online-mode и прежний плагин входа, если сервер уходит от VoidRP."
  exit 0
fi

need curl; need sha256sum; need sha512sum; need unzip
SECRET="$(find_secret)"
[ -n "$SECRET" ] || { c_err "не нашёл секрет сервера в конфигах VoidRP — сначала подключите сервер (install.sh из «Интеграции»)"; exit 1; }
AUTH_HEADER="X-Game-Auth-Secret: $SECRET"

BUNDLE="$(curl -fsSL -H "$AUTH_HEADER" "$API/game-sync/integration/bundle")" || { c_err "бэкенд не принял секрет — скачайте свежие конфиги в «Интеграции»"; exit 1; }
RUNNING=0; server_running && RUNNING=1
while read -r tag kind level name want filename url; do
  [ "$tag" = FILE ] || continue
  if [ "$DRY" = 1 ]; then dry_check "$kind" "$name" "$want" "$filename"; continue; fi
  place_jar "$kind" "$level" "$name" "$want" "$filename" "$url" || true
done <<<"$BUNDLE"
[ -n "$BACKUP" ] && echo "Старые файлы — в ${BACKUP#$DIR/}"
[ "$WAITING" = 1 ] && echo "Новые версии подменятся при следующем перезапуске сервера."
[ "$DRY" = 0 ] && { crontab -l 2>/dev/null | grep -qF "# voidrp-update $DIR" || echo "Обновлять каждую ночь само: добавьте --install-cron"; }
exit 0
'''

DOCTOR = r'''#!/usr/bin/env bash
# VoidRP: проверка сервера. Печатает отчёт, который можно вставить в чат поддержки;
# с --send он появится в «Интеграции» (нужен секрет в конфиге плагина VoidRP).
#   curl -fsSL __API__/integration/voidrp-doctor.sh | bash -s -- [папка сервера] [--send]
set -uo pipefail
API="__API__"
ARGS=(); SEND=0
for a in "$@"; do case "$a" in --send) SEND=1 ;; *) ARGS+=("$a") ;; esac; done
DIR="${ARGS[0]:-$PWD}"
OUT="$(mktemp)"
say() { printf '%s\n' "$*" | tee -a "$OUT"; }
okk() { say "[ok]   $*"; }
bad() { say "[!!]   $*"; }
inf() { say "[..]   $*"; }

say "VoidRP doctor · $(date -u '+%Y-%m-%d %H:%M UTC') · $(uname -sr)"
[ -f "$DIR/server.properties" ] && okk "папка сервера: $DIR" || bad "в $DIR нет server.properties"

# Запущен ли сервер из этой папки — и на какой Java.
RUN_PID=""; ABS="$(cd "$DIR" 2>/dev/null && pwd)"
for p in $(pgrep -x java 2>/dev/null); do [ "$(readlink "/proc/$p/cwd" 2>/dev/null)" = "$ABS" ] && RUN_PID="$p"; done

# Ядро и версия Minecraft: version_history.json (Paper), иначе имя jar ядра (paper-26.2-124.jar).
MC=""; BUILD=""; CURV=""
if [ -f "$DIR/version_history.json" ]; then
  CURV="$(grep -o '"currentVersion"[^,}]*' "$DIR/version_history.json" | sed -E 's/.*: *"([^"]*)".*/\1/')"
  MC="$(sed -nE 's/.*\(MC: ([0-9.]+)\).*/\1/p' <<<"$CURV")"
  BUILD="$(sed -nE 's/^[0-9.]+-([0-9]+)-.*/\1/p; s/^git-[A-Za-z]+-([0-9]+).*/\1/p' <<<"$CURV" | head -1)"
fi
CORE_JAR="$( { [ -n "$RUN_PID" ] && tr '\0' '\n' < "/proc/$RUN_PID/cmdline" | grep -m1 '\.jar$'; ls "$DIR" 2>/dev/null | grep -m1 -iE '^(paper|folia|purpur)-[0-9.]+-[0-9]+\.jar$'; } | head -1)"
CORE_JAR="$(basename "${CORE_JAR:-}")"
if [ -z "$MC" ] && [[ "$CORE_JAR" =~ ^([A-Za-z]+)-([0-9.]+)-([0-9]+)\.jar$ ]]; then
  MC="${BASH_REMATCH[2]}"; BUILD="${BASH_REMATCH[3]}"; CURV="${BASH_REMATCH[1]} $MC #$BUILD"
fi
[ -n "$CURV" ] && inf "ядро: $CURV" || { [ -n "$CORE_JAR" ] && inf "ядро: $CORE_JAR"; }
if [ -n "$MC" ] && [ -n "$BUILD" ] && grep -qi paper <<<"$CURV $CORE_JAR"; then
  LATEST="$(curl -fsS -m 10 "https://fill.papermc.io/v3/projects/paper/versions/$MC/builds/latest" 2>/dev/null | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)"
  if [ -n "$LATEST" ]; then
    if [ "$BUILD" -ge "$LATEST" ] 2>/dev/null; then okk "Paper $MC: свежая сборка #$BUILD"
    elif [ $((LATEST - BUILD)) -ge 20 ] 2>/dev/null; then bad "Paper $MC: сборка #$BUILD, вышла #$LATEST — обновите ядро (исправления безопасности и вылетов)"
    else inf "Paper $MC: сборка #$BUILD, есть #$LATEST"; fi
  fi
fi

JAVA_BIN="$( [ -n "$RUN_PID" ] && readlink "/proc/$RUN_PID/exe" || command -v java || true)"
if [ -n "$JAVA_BIN" ] && [ -x "$JAVA_BIN" ]; then
  JL="$("$JAVA_BIN" -version 2>&1 | head -1)"; JV="$(sed -E 's/.*version "([0-9]+).*/\1/' <<<"$JL")"
  NEED=21; case "$MC" in 2[6-9].*|[3-9][0-9].*) NEED=25 ;; 1.20.[5-6]|1.21*) NEED=21 ;; 1.1[89]*|1.20|1.20.[1-4]) NEED=17 ;; esac
  WHO="$([ -n "$RUN_PID" ] && echo "сервер работает на" || echo "Java в PATH:")"
  if [ -n "$MC" ] && [ "${JV:-0}" -lt "$NEED" ] 2>/dev/null; then bad "$WHO Java $JV, а Minecraft $MC нужна Java $NEED+"; else okk "$WHO $JL"; fi
else bad "java не найдена в PATH"; fi

# Память: сколько есть у машины и сколько отдано серверу (-Xmx запущенного процесса).
if command -v free >/dev/null 2>&1; then
  read -r _ MT _ _ _ _ MA <<<"$(free -m | awk 'NR==2')"
  XMX="$( [ -n "$RUN_PID" ] && tr '\0' '\n' < "/proc/$RUN_PID/cmdline" | grep -m1 '^-Xmx' | cut -c5- || true)"
  inf "память: всего ${MT} МБ, свободно ${MA} МБ${XMX:+, серверу отдано $XMX}"
  [ "${MA:-0}" -lt 512 ] 2>/dev/null && bad "свободной памяти меньше 512 МБ — сервер может упасть, а система начнёт убивать процессы"
fi
for t in curl unzip sha256sum; do command -v $t >/dev/null 2>&1 || bad "нет программы $t"; done

HOST="$(sed -E 's#^https?://([^/:]+).*#\1#' <<<"$API")"
getent hosts "$HOST" >/dev/null 2>&1 && okk "DNS: $HOST → $(getent hosts "$HOST" | awk '{print $1; exit}')" || bad "DNS: $HOST не находится"
HDR="$(curl -sS -m 10 -D - -o /dev/null "$API/servers" 2>&1)"
if grep -q "^HTTP.* 200" <<<"$HDR"; then
  okk "HTTPS до API: работает"
  SRV_DATE="$(grep -i '^date:' <<<"$HDR" | cut -d' ' -f2- | tr -d '\r')"
  if [ -n "$SRV_DATE" ]; then
    SKEW=$(( $(date +%s) - $(date -d "$SRV_DATE" +%s 2>/dev/null || date +%s) ))
    [ "${SKEW#-}" -le 60 ] && okk "часы: расхождение ${SKEW} с" || bad "часы отстают или спешат на ${SKEW} с — включите NTP (timedatectl set-ntp true)"
  fi
else bad "HTTPS до API не работает: $(head -1 <<<"$HDR")"; fi

if [ -f "$DIR/server.properties" ]; then
  P() { grep -m1 "^$1=" "$DIR/server.properties" | cut -d= -f2-; }
  inf "server-port=$(P server-port) online-mode=$(P online-mode) enforce-secure-profile=$(P enforce-secure-profile)"
  [ "$(P online-mode)" = "false" ] || bad "online-mode не false: игроки VoidRP без лицензии не зайдут"
  if [ "$(P enable-rcon)" = "true" ]; then
    RP="$(P rcon.port)"; RP="${RP:-25575}"
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "^(0\.0\.0\.0|\*|\[::\]):$RP$"; then
      bad "RCON слушает все адреса на порту $RP — закройте фаерволом или выключите (консоль идёт через VoidRpPerms)"
    else inf "RCON включён на порту $RP (не на всех адресах)"; fi
  else okk "RCON выключен"; fi
  SP="$(P server-port)"; SP="${SP:-25565}"
  if [ -n "${RUN_PID:-}" ]; then
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq ":$SP$"; then okk "сервер запущен и слушает порт $SP"
    else bad "сервер запущен, но порт $SP не слушается — ещё грузится или занят другим процессом"; fi
  else inf "сервер сейчас не запущен"; fi
fi

if [ -d "$DIR/plugins" ]; then
  say "плагины:"
  for j in "$DIR"/plugins/*.jar; do
    [ -f "$j" ] || continue
    y="$(unzip -p "$j" plugin.yml paper-plugin.yml 2>/dev/null)"
    n="$(grep -m1 -E '^name:' <<<"$y" | sed -E "s/^name:[[:space:]]*['\"]?([^'\" ]+).*/\1/")"
    v="$(grep -m1 -E '^version:' <<<"$y" | sed -E "s/^version:[[:space:]]*['\"]?([^'\"]+).*/\1/")"
    say "         ${n:-?} ${v:-?} ($(basename "$j"))"
    case "$n" in
      AuthMe|AuthMeReloaded|nLogin|LibreLogin|JPremium|FastLogin) bad "$n мешает входу VoidRpAuth — уберите его";;
      SkinsRestorer) bad "SkinsRestorer: VoidRpAuth 1.4+ сам ставит скины из аккаунта VoidRP — уберите его";;
    esac
  done
  [ -d "$DIR/plugins/update" ] && [ -n "$(ls -A "$DIR/plugins/update" 2>/dev/null)" ] && inf "ждут перезапуска в plugins/update: $(ls "$DIR/plugins/update" | tr '\n' ' ')"
fi
# Наши плагины против свежих сборок (по секрету из конфига, как в update.sh).
SECRET=""
for f in plugins/VoidRpPerms/config.yml plugins/VoidRpAuth/config.yml plugins/VoidRpGuard/config.yml config/voidrp-auth-bridge.properties; do
  [ -f "$DIR/$f" ] || continue
  SECRET="$(grep -m1 -E '^\s*(secret|game-auth-secret|gameSecret)\s*[:=]' "$DIR/$f" | sed -E "s/^[^:=]*[:=][[:space:]]*['\"]?([^'\" ]+).*/\1/")"
  [ -n "$SECRET" ] && break
done
if [ -n "$SECRET" ]; then
  BUNDLE="$(curl -fsS -m 15 -H "X-Game-Auth-Secret: $SECRET" "$API/game-sync/integration/bundle" 2>/dev/null)"
  if [ -z "$BUNDLE" ]; then bad "бэкенд не принял секрет из конфига — скачайте свежие конфиги в «Интеграции»"
  else
    okk "секрет из конфига принят"
    OUTD=""
    while read -r tag kind level name want filename url; do
      [ "$tag" = FILE ] && [ "$kind" = plugin ] || continue
      case "$name" in VoidRp*) ;; *) continue ;; esac
      j=""
      for c in "$DIR"/plugins/*.jar; do
        [ -f "$c" ] || continue
        [ "$(unzip -p "$c" plugin.yml paper-plugin.yml 2>/dev/null | grep -m1 -E '^name:' | sed -E "s/^name:[[:space:]]*['\"]?([^'\" ]+).*/\1/")" = "$name" ] && { j="$c"; break; }
      done
      [ -z "$j" ] && continue
      case "$want" in sha256:*) h="$(sha256sum "$j" | cut -d' ' -f1)"; w="${want#sha256:}" ;; sha512:*) h="$(sha512sum "$j" | cut -d' ' -f1)"; w="${want#sha512:}" ;; *) continue ;; esac
      [ "$h" = "$w" ] || OUTD="$OUTD $name→$filename"
    done <<<"$BUNDLE"
    [ -n "$OUTD" ] && bad "есть обновления:$OUTD — curl -fsSL $API/integration/voidrp-update.sh | bash" || okk "плагины VoidRP свежие"
  fi
else inf "секрета VoidRP в конфигах нет — сервер ещё не подключён"; fi
crontab -l 2>/dev/null | grep -q "voidrp-update" && okk "ночное автообновление (cron) включено" || true

[ -d "$DIR/mods" ] && inf "модов: $(ls "$DIR"/mods/*.jar 2>/dev/null | wc -l)$(ls "$DIR"/mods/voidrp_auth_bridge*.jar >/dev/null 2>&1 && echo ', voidrp-auth-bridge стоит' || echo ', voidrp-auth-bridge НЕ найден')"
df -h "$DIR" 2>/dev/null | awk 'NR==2 {print "[..]   диск: занято "$5", свободно "$4}' | tee -a "$OUT"

if [ "$SEND" = 1 ]; then
  if [ -z "$SECRET" ]; then echo "Не отправлено: нет секрета в конфигах VoidRP."
  elif curl -fsS -m 15 -H "X-Game-Auth-Secret: $SECRET" -H "Content-Type: text/plain; charset=utf-8" --data-binary @"$OUT" "$API/game-sync/integration/doctor" >/dev/null; then
    echo "Отчёт отправлен — он в «Интеграции»."
  else echo "Не удалось отправить отчёт."; fi
fi
rm -f "$OUT"
'''


def render(template: str, **values: Any) -> str:
    out = template.replace("__API__", _api())
    for k, v in values.items():
        out = out.replace(f"__{k.upper()}__", re.sub(r"[^\w .:/«»()-]", "", str(v)))
    return out
