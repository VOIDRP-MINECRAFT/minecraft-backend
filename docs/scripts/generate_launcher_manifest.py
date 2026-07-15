#!/usr/bin/env python3
"""
Generate VoidRP launcher manifest from pack directory.
Port of generate_launcher_manifest.ps1 — same matching logic, Linux defaults.

Usage:
    python3 generate_launcher_manifest.py
    python3 generate_launcher_manifest.py --pack-root /custom/path --pack-version 1.0.1
"""

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import sys
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Tables — keep in sync with generate_launcher_manifest.ps1
# ---------------------------------------------------------------------------

ALWAYS_OVERWRITE_PREFIXES = [
    "config/fancymenu/",
    "config/immediatelyfast.json",  # hud_batching=false required for Iris shader screen
    "config/mcef.properties",       # MCEF download mirror — must stay pointed at void-rp.ru
]

# Static media under the alwaysOverwrite prefixes never changes on the client, yet the
# flag forces it to re-download every launch (~40 MB of fancymenu panoramas/logos/icons).
# Exclude these extensions so only the small mutable config text/db keeps being re-asserted;
# the binaries fall back to normal hash-based sync (download once, skip forever).
ALWAYS_OVERWRITE_SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".icns", ".ico",
    ".ogg", ".wav", ".mp3", ".ttf", ".otf",
}

REQUIRED_LOCKED_MODS = {
    "FancyMod":  {"displayName": "FancyMod (Античит)", "description": "Обязательный античит-модуль. Нельзя отключить."},
    "AntiFraud": {"displayName": "AntiFraud",          "description": "Обязательный модуль защиты. Нельзя отключить."},
    "webgui":    {"displayName": "WebGUI",              "description": "Встроенный браузер для игрового интерфейса VoidRP. Нельзя отключить."},
}

OPTIONAL_MODS = {
    # Производительность / рендеринг
    "Embeddium":                {"displayName": "Embeddium",                  "description": "Увеличение FPS (порт Sodium для NeoForge)."},
    "Rubidium":                 {"displayName": "Rubidium",                   "description": "Увеличение FPS (порт Sodium для Forge)."},
    "Oculus":                   {"displayName": "Oculus (Шейдеры)",           "description": "Поддержка шейдерпаков (порт Iris для Forge)."},
    "Sodium Extra":             {"displayName": "Sodium Extra",               "description": "Дополнительные настройки Sodium."},
    "Memory Leak Fix":          {"displayName": "Memory Leak Fix",            "description": "Исправляет утечки памяти в Minecraft."},
    "Dynamic FPS":              {"displayName": "Dynamic FPS",                "description": "Снижает FPS когда игра свёрнута или не в фокусе."},
    "Exordium":                 {"displayName": "Exordium",                   "description": "Оптимизация рендеринга интерфейса и HUD."},
    "Krypton":                  {"displayName": "Krypton",                    "description": "Оптимизация сетевого стека Minecraft."},
    "LazyDFU":                  {"displayName": "LazyDFU",                    "description": "Ускорение запуска игры."},
    "Smooth Boot":              {"displayName": "Smooth Boot",                "description": "Сглаживает нагрузку CPU при загрузке."},
    "Noisium":                  {"displayName": "Noisium",                    "description": "Ускорение генерации мира."},
    "Canary":                   {"displayName": "Canary",                     "description": "Оптимизация логики сервера и клиента."},
    "Radon":                    {"displayName": "Radon",                      "description": "Оптимизация движка освещения (Phosphor port)."},
    "Starlight":                {"displayName": "Starlight",                  "description": "Полная переработка движка освещения."},
    # Мини-карта / карта мира
    "JourneyMap":               {"displayName": "JourneyMap",                 "description": "Карта мира и мини-карта в реальном времени."},
    "VoxelMap":                 {"displayName": "VoxelMap",                   "description": "Мини-карта и карта мира."},
    # HUD / интерфейс
    "WAILA":                    {"displayName": "WAILA",                      "description": "Информация о блоках при наведении."},
    "WTHIT":                    {"displayName": "WTHIT",                      "description": "Информация о блоках при наведении."},
    "AppleSkin":                {"displayName": "AppleSkin",                  "description": "Отображение сытости и восстановления здоровья от еды."},
    "Inventory HUD":            {"displayName": "Inventory HUD+",             "description": "Дисплей инвентаря, зелий и брони прямо в игре."},
    "Durability Viewer":        {"displayName": "Durability Viewer",          "description": "Прочность предметов в HUD."},
    "Status Effect Bars":       {"displayName": "Status Effect Bars",         "description": "Полоски эффектов зелий в HUD."},
    "Chat Heads":               {"displayName": "Chat Heads",                 "description": "Аватарки игроков рядом с их сообщениями в чате."},
    "Zoomify":                  {"displayName": "Zoomify",                    "description": "Приближение камеры (как в OptiFine)."},
    "Ok Zoomer":                {"displayName": "Ok Zoomer",                  "description": "Приближение камеры."},
    "Mouse Tweaks":             {"displayName": "Mouse Tweaks",               "description": "Удобное управление инвентарём мышью."},
    "Better Ping Display":      {"displayName": "Better Ping Display",        "description": "Показывает пинг в мс в списке игроков."},
    "Screenshot to Clipboard":  {"displayName": "Screenshot to Clipboard",    "description": "Скриншоты копируются в буфер обмена."},
    "Mod Menu":                 {"displayName": "Mod Menu",                   "description": "Список установленных модов в главном меню."},
    "Catalogue":                {"displayName": "Catalogue",                  "description": "Экран списка модов с поиском."},
    "Controlify":               {"displayName": "Controlify",                 "description": "Поддержка геймпадов."},
    "Simple Voice Chat":        {"displayName": "Simple Voice Chat",          "description": "Голосовой чат в игре."},
    "Plasmo Voice":             {"displayName": "Plasmo Voice",               "description": "Голосовой чат в игре."},
    # Визуальные / атмосфера
    "LambDynamicLights":        {"displayName": "LambDynamicLights",          "description": "Динамическое освещение от предметов в руках."},
    "Dynamic Lights":           {"displayName": "Dynamic Lights",             "description": "Динамическое освещение от предметов в руках."},
    "Falling Leaves":           {"displayName": "Falling Leaves",             "description": "Анимация опадающих листьев с деревьев."},
    "Sound Physics Remastered": {"displayName": "Sound Physics Remastered",   "description": "Реалистичная физика и эхо звуков."},
    "Sound Physics":            {"displayName": "Sound Physics Remastered",   "description": "Реалистичная физика и эхо звуков."},
    "Ambient Sounds":           {"displayName": "Ambient Sounds",             "description": "Атмосферные звуки окружения в разных биомах."},
    "Presence Footsteps":       {"displayName": "Presence Footsteps",         "description": "Реалистичные звуки шагов по материалу блока."},
    "Blur":                     {"displayName": "Blur",                       "description": "Размытие фона при открытии меню."},
    "First Person Model":       {"displayName": "First Person Model",         "description": "Видимое тело от первого лица."},
    # Разное / QoL
    "Hold My Items":            {"displayName": "Hold My Items",              "description": "Ручки ручки."},
    "Do a Barrel Roll":         {"displayName": "Do a Barrel Roll",           "description": "Выполнение жестких флипчиков при полёте."},
    "Enchantment Descriptions": {"displayName": "Enchantment Descriptions",   "description": "Описания заклинаний на книгах и предметах."},
    "Toast Control":            {"displayName": "Toast Control",              "description": "Управление всплывающими подсказками."},
    "Better F3":                {"displayName": "BetterF3",                   "description": "Улучшенный экран F3 (debug)."},
    "BetterF3":                 {"displayName": "BetterF3",                   "description": "Улучшенный экран F3 (debug)."},
    "forgematica":              {"displayName": "Forgematica",                "description": "Схематика все что надо для построек!"},
    "InventoryParticles":       {"displayName": "InventoryParticles",         "description": "Анимированные предметы в инвентаре!"},
    "InventoryInteractions":       {"displayName": "InventoryInteractions",         "description": "Анимированные предметы в инвентаре 2!"},
}

SERVER_ONLY_MODS = [
    "bukkit", "craftbukkit", "spigot", "paper", "purpur", "mohist",
    "arclight", "ketting", "luckperms", "essentialsx", "worldguard",
    "worldedit", "coreprotect", "plugmanx", "viaversion", "geyser",
    "bluemap", "dynmap", "authme", "nlogin",
]

EXCLUDE_PREFIXES = [
    ".mixin.out/", "logs/", "log/", "crash-reports/", "screenshots/", "saves/",
    "downloads/", "tmp/", "temp/", "debug/", "fancymenu_data/", "local/",
    "dynamic-resource-pack-cache/", "moddata/", "moonlight-global-datapacks/",
    "patchouli_books/", "server-resource-packs/", "natives/", "telemetry/",
    "journeymap/data/", "xaeroworldmap/", "xaerominimap/", "xaero/", "mods/.connector/",
]

EXCLUDE_FILENAMES = {
    ".ds_store", "thumbs.db", "desktop.ini", "usercache.json", "servers.dat_old",
    "command_history.txt", "patchouli_data.json", "immersivetips.json", "hash.txt",
}

EXCLUDE_PATTERNS = [
    "*.tmp", "*.bak", "*.log", "*.log.gz", "*.info", "*.pid",
    "win_event*.txt", "renderer_pid*.tmp", "successful_launch_pid*.tmp",
]

# ---------------------------------------------------------------------------
# Helpers — exact port of PS functions
# ---------------------------------------------------------------------------

def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")

def _encode_url(rel: str) -> str:
    return "/".join(quote(seg, safe="") for seg in rel.split("/"))

def should_exclude(rel: str) -> bool:
    if not rel:
        return True
    n = _norm(rel).lower()
    for p in EXCLUDE_PREFIXES:
        if n.startswith(p.lower()):
            return True
    fn = os.path.basename(n)
    if not fn:
        return True
    if fn in EXCLUDE_FILENAMES:
        return True
    for pat in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(fn, pat):
            return True
    return False

def _under_overwrite_prefix(n: str) -> bool:
    return any(n.startswith(p.lower()) for p in ALWAYS_OVERWRITE_PREFIXES)

def should_always_overwrite(rel: str) -> bool:
    n = _norm(rel).lower()
    if not _under_overwrite_prefix(n):
        return False
    return os.path.splitext(n)[1] not in ALWAYS_OVERWRITE_SKIP_EXTS

def should_manage(rel: str) -> bool:
    # Static media under the overwrite prefixes: hash-synced instead of blindly forced.
    # Downloaded once, skipped while unchanged, and re-pulled only if we ship a new version.
    n = _norm(rel).lower()
    if not _under_overwrite_prefix(n):
        return False
    return os.path.splitext(n)[1] in ALWAYS_OVERWRITE_SKIP_EXTS

def _mod_slug(filename: str) -> str:
    stem = os.path.splitext(filename)[0].lower()
    stem = re.sub(r'[-_+][0-9].*$', '', stem)
    stem = re.sub(r'[-_](forge|neoforge|fabric|quilt|mc\d.*)$', '', stem)
    return stem

def _compact(value: str) -> str:
    return re.sub(r'[-_ ]', '', value.lower())

def _key_matches(slug: str, compact_slug: str, key: str) -> bool:
    kl   = key.lower()
    ckl  = _compact(key)
    return (
        compact_slug == ckl
        or slug == kl
        or slug.startswith(kl + '-')
        or slug.startswith(kl + '_')
    )

def classify_mod(rel: str):
    n = _norm(rel)
    if not re.match(r'^mods/[^/]+\.jar$', n):
        return None

    slug    = _mod_slug(os.path.basename(n))
    compact = _compact(slug)

    for key in SERVER_ONLY_MODS:
        ckl = _compact(key)
        if compact == ckl or slug == key or slug.startswith(key+'-') or slug.startswith(key+'_'):
            return {"serverOnly": True}

    for key, info in REQUIRED_LOCKED_MODS.items():
        if _key_matches(slug, compact, key):
            return {"optional": True, "required": True, **info}

    for key, info in OPTIONAL_MODS.items():
        if _key_matches(slug, compact, key):
            return {"optional": True, "required": False, **info}

    return None  # required-hidden

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
class C:
    CYAN  = "\033[96m";  GREEN = "\033[92m"; YELLOW = "\033[93m"
    GRAY  = "\033[90m";  RED   = "\033[91m"; RESET  = "\033[0m"

# ---------------------------------------------------------------------------
# Multi-server DB loader
# ---------------------------------------------------------------------------

DEFAULT_ENV_PATH = "/home/mironoouv/minecraft/minecraft_backend/.env"
DEFAULT_MANIFESTS_DIR = "/home/mironoouv/launcher/manifests"


def _read_database_url(env_path: str) -> str | None:
    if not os.path.isfile(env_path):
        return None
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
                # psycopg.connect wants a libpq URL, not the SQLAlchemy '+psycopg' variant
                return url.replace("postgresql+psycopg://", "postgresql://")
    return None


def _load_servers_from_db(env_path: str, slug: str | None) -> list[dict]:
    """Read visible game_servers rows for manifest generation."""
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError:
        sys.exit(
            "ERROR: psycopg not available. Run with the backend venv, e.g.\n"
            "  /home/mironoouv/minecraft/minecraft_backend/.venv/bin/python "
            "scripts/generate_launcher_manifest.py --all"
        )
    db_url = _read_database_url(env_path)
    if not db_url:
        sys.exit(f"ERROR: DATABASE_URL not found in {env_path}")

    cols = [
        "slug", "name", "host", "port", "mc_version", "loader", "java_version",
        "neoforge_version", "pack_root", "pack_base_url", "pack_version",
        "min_launcher_version", "is_default",
    ]
    where = "WHERE is_visible = true"
    params: tuple = ()
    if slug:
        where = "WHERE slug = %s"
        params = (slug,)
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM game_servers {where} ORDER BY sort_order", params)
        rows = cur.fetchall()
    if not rows:
        sys.exit(f"ERROR: no matching game_servers rows ({'slug='+slug if slug else 'visible'})")
    return [dict(zip(cols, r)) for r in rows]


def _meta_from_server(row: dict, args) -> dict:
    # CLI override wins if given, else the server's own DB value, else a safe default.
    neoforge = args.neoforge_version or row.get("neoforge_version") or "21.1.232"
    loader = row.get("loader") or "neoforge"
    # Derive the launcher profile (CmlLib version id) from THIS server's loader version,
    # not a global CLI default — otherwise --all stamps every server (e.g. abyss on 26.2)
    # with the default 21.1.x profile. Explicit --launcher-profile-id still overrides.
    profile_id = args.launcher_profile_id or f"{loader}-{neoforge}"
    return {
        "packName":           row.get("name") or "VoidRP",
        "packVersion":        row.get("pack_version") or "1.0.0",
        "packDisplayVersion": args.pack_display_version,
        "launcherProfileId":  profile_id,
        "neoForgeVersion":    neoforge,
        "fmlVersion":         args.fml_version,
        "neoFormVersion":     args.neoform_version,
        "minecraftVersion":   row.get("mc_version") or "1.21.1",
        "loader":             row.get("loader") or "neoforge",
        "javaVersion":        int(row.get("java_version") or 21),
        "minLauncherVersion": row.get("min_launcher_version") or "0.1.0",
        "server":             {"host": row.get("host"), "port": int(row.get("port") or 25565)},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _generate_one(pack_root: str, base_url: str, output: str, meta: dict) -> None:
    """Scan pack_root and write a single per-server manifest to output."""
    if not os.path.isdir(pack_root):
        sys.exit(f"ERROR: pack-root not found: {pack_root}")

    os.makedirs(os.path.dirname(output), exist_ok=True)

    files               = []
    mods_optional       = []
    mods_required_locked = []
    mods_required_hidden = []
    mods_server_only    = []
    processed = skipped = errors = always_overwrite_count = managed_count = 0

    for root, dirs, filenames in os.walk(pack_root):
        dirs.sort()
        for filename in sorted(filenames):
            full_path = os.path.join(root, filename)
            rel = os.path.relpath(full_path, pack_root).replace("\\", "/")

            try:
                if should_exclude(rel):
                    skipped += 1
                    continue

                cls = classify_mod(rel)
                if cls and cls.get("serverOnly"):
                    mods_server_only.append(rel)
                    print(f"WARNING: EXCLUDED server-only: {rel}", file=sys.stderr)
                    skipped += 1
                    continue

                sha  = _sha256(full_path)
                size = os.path.getsize(full_path)
                url  = f"{base_url}/{_encode_url(rel)}"

                entry = {"path": rel, "size": size, "sha256": sha, "url": url}

                if should_always_overwrite(rel):
                    entry["alwaysOverwrite"] = True
                    always_overwrite_count += 1
                elif should_manage(rel):
                    entry["managed"] = True
                    managed_count += 1

                if cls and cls.get("optional"):
                    entry["optional"]     = True
                    entry["required"]     = cls["required"]
                    entry["displayName"]  = cls["displayName"]
                    entry["description"]  = cls["description"]
                    label = f"{rel}  ->  {cls['displayName']}"
                    (mods_required_locked if cls["required"] else mods_optional).append(label)
                else:
                    if re.match(r'^mods/[^/]+\.jar$', _norm(rel)):
                        mods_required_hidden.append(rel)

                files.append(entry)
                processed += 1

            except Exception as e:
                errors += 1
                print(f"WARNING: FAILED: {full_path} -- {e}", file=sys.stderr)

    for rel in mods_required_hidden:
        slug = _mod_slug(os.path.basename(rel))
        print(f"  [?] неизвестный мод: {slug}  ({rel})")

    files.sort(key=lambda x: x["path"].lower())

    manifest = {
        "packName":           meta["packName"],
        "packVersion":        meta["packVersion"],
        "packDisplayVersion": meta["packDisplayVersion"],
        "launcherProfileId":  meta["launcherProfileId"],
        "neoForgeVersion":    meta["neoForgeVersion"],
        "fmlVersion":         meta["fmlVersion"],
        "neoFormVersion":     meta["neoFormVersion"],
        "buildDateUtc":       datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "minecraftVersion":   meta["minecraftVersion"],
        "loader":             meta["loader"],
        "javaVersion":        meta["javaVersion"],
        "minLauncherVersion": meta["minLauncherVersion"],
        "fullSyncFallback":   True,
        "notes":              f"VoidRP launcher manifest for {meta['packName']}",
        "server":             meta["server"],
        "files":              files,
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Report
    print()
    print(C.CYAN + "===========================================================" + C.RESET)
    print(C.CYAN + f"  {output}" + C.RESET)
    print(C.CYAN + "===========================================================" + C.RESET)
    print(f"  Файлов: {processed} обработано, {skipped} пропущено, {errors} ошибок")
    print(f"  AlwaysOverwrite: {always_overwrite_count}   Managed: {managed_count}   Всего: {len(files)}")
    print()

    if mods_required_locked:
        print(C.YELLOW + "-- ЗАБЛОКИРОВАННЫЕ ---------------------------------------------------" + C.RESET)
        for m in sorted(mods_required_locked): print(C.YELLOW + f"  {m}" + C.RESET)
        print()

    if mods_optional:
        print(C.GREEN + "-- ОПЦИОНАЛЬНЫЕ ------------------------------------------------------" + C.RESET)
        for m in sorted(mods_optional): print(C.GREEN + f"  {m}" + C.RESET)
        print()

    if mods_required_hidden:
        print(C.GRAY + "-- ОБЯЗАТЕЛЬНЫЕ СКРЫТЫЕ ----------------------------------------------" + C.RESET)
        for m in sorted(mods_required_hidden): print(C.GRAY + f"  {m}" + C.RESET)
        print()

    if mods_server_only:
        print(C.RED + "-- СЕРВЕРНЫЕ (исключены) ---------------------------------------------" + C.RESET)
        for m in sorted(mods_server_only): print(C.RED + f"  {m}" + C.RESET)
        print()

    print(C.CYAN + f"  Опциональных: {len(mods_optional)}  |  Заблокированных: {len(mods_required_locked)}  |  Скрытых: {len(mods_required_hidden)}" + C.RESET)
    print()
    if mods_required_hidden:
        print("  [?] — неопознанные моды выведены выше. Добавь slug в OPTIONAL_MODS.")
        print()


def main():
    ap = argparse.ArgumentParser(description="Generate VoidRP launcher manifest(s)")
    # Multi-server (DB-driven) selection
    ap.add_argument("--server-slug", default=None, help="Generate manifest for one server (reads game_servers)")
    ap.add_argument("--all", action="store_true", help="Generate manifests for all visible servers")
    ap.add_argument("--env-path", default=DEFAULT_ENV_PATH, help="Backend .env with DATABASE_URL")
    ap.add_argument("--manifests-dir", default=DEFAULT_MANIFESTS_DIR)
    # Launcher-specific defaults (not stored per-server in DB)
    ap.add_argument("--pack-display-version", default="VOID-RP")
    # Default None → derive per-server from the DB loader version; pass to force-override.
    ap.add_argument("--launcher-profile-id",  default=None)
    ap.add_argument("--neoforge-version",     default=None)
    ap.add_argument("--fml-version",          default="4.0.42")
    ap.add_argument("--neoform-version",      default="1.21.1-20240808.144430")
    # Legacy single-manifest mode (used only when neither --all nor --server-slug given)
    ap.add_argument("--pack-root",            default="/home/mironoouv/launcher/pack")
    ap.add_argument("--output",               default="/home/mironoouv/launcher/manifests/manifest.json")
    ap.add_argument("--base-url",             default="https://void-rp.ru/launcher/pack")
    ap.add_argument("--pack-name",            default="VoidRP Better MC 5")
    ap.add_argument("--pack-version",         default="1.0.0")
    ap.add_argument("--mc-version",           default="1.21.1")
    ap.add_argument("--loader",               default="neoforge")
    ap.add_argument("--java-version",         type=int, default=21)
    ap.add_argument("--server-host",          default="void-rp.ru")
    ap.add_argument("--server-port",          type=int, default=25565)
    ap.add_argument("--min-launcher-version", default="0.1.0")
    args = ap.parse_args()

    if args.all or args.server_slug:
        servers = _load_servers_from_db(args.env_path, args.server_slug)
        for row in servers:
            slug = row["slug"]
            pack_root = row.get("pack_root") or os.path.join("/home/mironoouv/launcher/pack", slug)
            base_url = row.get("pack_base_url") or f"https://void-rp.ru/launcher/pack/{slug}"
            output = os.path.join(args.manifests_dir, f"{slug}.json")
            print(C.CYAN + f"\n### Server '{slug}'  pack={pack_root}" + C.RESET)
            _generate_one(pack_root, base_url, output, _meta_from_server(row, args))
            # Back-compat: the default server also writes the legacy manifest.json
            if row.get("is_default"):
                legacy = os.path.join(args.manifests_dir, "manifest.json")
                import shutil
                shutil.copyfile(output, legacy)
                print(C.GRAY + f"  (default) copied -> {legacy}" + C.RESET)
        return

    # Legacy single-server mode
    meta = {
        "packName":           args.pack_name,
        "packVersion":        args.pack_version,
        "packDisplayVersion": args.pack_display_version,
        "launcherProfileId":  args.launcher_profile_id or "neoforge-21.1.232",
        "neoForgeVersion":    args.neoforge_version or "21.1.232",
        "fmlVersion":         args.fml_version,
        "neoFormVersion":     args.neoform_version,
        "minecraftVersion":   args.mc_version,
        "loader":             args.loader,
        "javaVersion":        args.java_version,
        "minLauncherVersion": args.min_launcher_version,
        "server":             {"host": args.server_host, "port": args.server_port},
    }
    _generate_one(args.pack_root, args.base_url, args.output, meta)


if __name__ == "__main__":
    main()
