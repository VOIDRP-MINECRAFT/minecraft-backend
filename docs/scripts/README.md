# Server-side operational scripts

Utility scripts that run on the VoidRP host alongside the backend. They live in
`/home/mironoouv/minecraft/scripts/` in production; this directory is the
version-controlled mirror so the code is backed up and reviewable.

Python scripts that touch the database (the manifest generators) expect the
backend's `DATABASE_URL` and are run with the backend venv:

```bash
minecraft_backend/.venv/bin/python scripts/<name>.py
```

## Launcher / modpack manifests

| Script | Description |
|--------|-------------|
| `generate_launcher_manifest.py` | Generates the launcher pack manifest (`manifest.json` / `<slug>.json`) from a server's `pack_root`. Reads `game_servers` from the DB. Classifies mods (optional / required-locked / server-only), sets `alwaysOverwrite` for mutable fancymenu config and `managed` for static fancymenu media (hash-synced, so updates reach clients without re-downloading unchanged assets). `--all` / `--server-slug <slug>`; legacy no-flag mode reads `/home/mironoouv/launcher/pack/`. |
| `generate_launcher_manifest.ps1` | Original PowerShell version of the above (Windows). The `.py` is the maintained port; keep matching logic (`OPTIONAL_MODS`, `REQUIRED_LOCKED_MODS`, `SERVER_ONLY_MODS`) in sync. |
| `generate_runtime_manifest.py` | Generates the per-platform Java runtime-seed manifest for the launcher's runtime bootstrap. Reads `/home/mironoouv/launcher/runtime-seed/`. |
| `generate_abyss_manifests.sh` | Wrapper that regenerates the manifests for the **VoidRP: Abyss** server (Minecraft 26.2, NeoForge 26.2.0.8-beta). |
| `generate_mods_list.py` | Scans a pack's `mods/` folder and emits a JSON mod list (id, name, description, version) for the site's server-guide "Mods" tab. Reads each jar's `META-INF/neoforge.mods.toml` (or legacy `mods.toml`). |

## Site data extraction (item icons / names / recipes)

| Script | Description |
|--------|-------------|
| `build_item_names.py` | Extracts `ru_ru.json` from every mod jar → `item_names.json` for the site. Also refreshes KubeJS textures. |
| `extract_item_textures.py` | Extracts item textures from mod jars → `VOIDRP-SITE/public/item-icons/{modid}/{name}.png`. |
| `fetch_missing_icons.py` | Finds and copies missing item icons from mod jars (item texture → block texture → fuzzy name match). |
| `parse_recipes.py` | Parses all KubeJS recipes from `server_scripts/` → `recipes.json` for the site. |

## Map markers (BlueMap / Dynmap)

| Script | Description |
|--------|-------------|
| `update_bluemap_wg_markers.py` | Reads WorldGuard regions, writes them as BlueMap markers, and colors each region with its nation's accent color fetched from the VoidRP API. |
| `bluemap_markers_daemon.py` | Daemon that watches `live/markers.json` and immediately re-injects WorldGuard regions from `wg-regions.json` (latency ≤ 0.5 s). |
| `update_dynmap_nation_colors.py` | Updates the Dynmap-WorldGuard ownerstyle config so each player's regions are colored in their nation's accent color. |

## Server lifecycle / watchdog

| Script | Description |
|--------|-------------|
| `minecraft_watchdog.sh` | Server watchdog: detects hangs/crashes, collects diagnostics, and invokes Claude. See `watchdog.txt` for notes. |
| `scheduled_restart.sh` | Planned server restart, run by cron at 04:00. |
| `watchdog_logrotate.sh` | Archives `watchdog.log` and prunes old archives (runs every 12 h). |
| `watchdog.txt` | Notes / configuration reference for the watchdog. |
