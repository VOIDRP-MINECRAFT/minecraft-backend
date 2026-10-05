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
#   curl -fsSL __API__/i/__TOKEN__ | bash -s -- [папка сервера] [--all]
# --all — поставить и необязательные плагины (античит VoidRpGuard с GrimAC и CoreProtect).
''' + _COMMON + r'''
ARGS=(); ALL=0
for a in "$@"; do case "$a" in --all) ALL=1 ;; *) ARGS+=("$a") ;; esac; done
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
# поэтому ссылка не нужна — можно ставить в cron:
#   curl -fsSL __API__/integration/voidrp-update.sh | bash -s -- [папка сервера] [--dry-run]
# На работающем Paper новые jar ложатся в plugins/update/ (подменятся при перезапуске),
# моды — только при остановленном сервере. Конфиги не трогает.
''' + _COMMON + r'''
ARGS=(); DRY=0
for a in "$@"; do case "$a" in --dry-run) DRY=1 ;; *) ARGS+=("$a") ;; esac; done
DIR="$(server_dir "${ARGS[0]:-}")"
need curl; need sha256sum; need sha512sum; need unzip

SECRET=""
for f in plugins/VoidRpPerms/config.yml plugins/VoidRpAuth/config.yml plugins/VoidRpGuard/config.yml config/voidrp-auth-bridge.properties; do
  [ -f "$DIR/$f" ] || continue
  SECRET="$(grep -m1 -E '^\s*(secret|game-auth-secret|gameSecret)\s*[:=]' "$DIR/$f" | sed -E "s/^[^:=]*[:=][[:space:]]*['\"]?([^'\" ]+).*/\1/")"
  [ -n "$SECRET" ] && break
done
[ -n "$SECRET" ] || { c_err "не нашёл секрет сервера в конфигах VoidRP — сначала подключите сервер (install.sh из «Интеграции»)"; exit 1; }
AUTH_HEADER="X-Game-Auth-Secret: $SECRET"

BUNDLE="$(curl -fsSL -H "$AUTH_HEADER" "$API/game-sync/integration/bundle")" || { c_err "бэкенд не принял секрет — скачайте свежие конфиги в «Интеграции»"; exit 1; }
RUNNING=0; server_running && RUNNING=1
while read -r tag kind level name want filename url; do
  [ "$tag" = FILE ] || continue
  if [ "$DRY" = 1 ]; then
    old="$(existing_jar "$kind" "$name")"
    if [ -n "$old" ] && hash_ok "$old" "$want"; then c_ok "$name: актуален"; else c_warn "$name: есть $filename${old:+ (стоит $(basename "$old"))}"; fi
    continue
  fi
  place_jar "$kind" "$level" "$name" "$want" "$filename" "$url" || true
done <<<"$BUNDLE"
[ -n "$BACKUP" ] && echo "Старые файлы — в ${BACKUP#$DIR/}"
[ "$WAITING" = 1 ] && echo "Новые версии подменятся при следующем перезапуске сервера."
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

if command -v java >/dev/null 2>&1; then okk "Java: $(java -version 2>&1 | head -1)"; else bad "java не найдена в PATH"; fi
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
[ -d "$DIR/mods" ] && inf "модов: $(ls "$DIR"/mods/*.jar 2>/dev/null | wc -l)$(ls "$DIR"/mods/voidrp_auth_bridge*.jar >/dev/null 2>&1 && echo ', voidrp-auth-bridge стоит' || echo ', voidrp-auth-bridge НЕ найден')"
df -h "$DIR" 2>/dev/null | awk 'NR==2 {print "[..]   диск: занято "$5", свободно "$4}' | tee -a "$OUT"

if [ "$SEND" = 1 ]; then
  SECRET=""
  for f in plugins/VoidRpPerms/config.yml plugins/VoidRpAuth/config.yml plugins/VoidRpGuard/config.yml config/voidrp-auth-bridge.properties; do
    [ -f "$DIR/$f" ] || continue
    SECRET="$(grep -m1 -E '^\s*(secret|game-auth-secret|gameSecret)\s*[:=]' "$DIR/$f" | sed -E "s/^[^:=]*[:=][[:space:]]*['\"]?([^'\" ]+).*/\1/")"
    [ -n "$SECRET" ] && break
  done
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
