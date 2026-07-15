# Серверные служебные скрипты

Утилиты, которые крутятся на хосте VoidRP рядом с бэкендом. В проде они лежат в
`/home/mironoouv/minecraft/scripts/`; этот каталог — их версия под гитом, чтобы
код был в бэкапе и его можно было ревьюить.

Python-скрипты, которые ходят в базу (генераторы манифестов), ожидают
`DATABASE_URL` бэкенда и запускаются его venv:

```bash
minecraft_backend/.venv/bin/python scripts/<имя>.py
```

> Как пересобирать манифесты лаунчера (актуальные команды по-русски) —
> см. **`КАК_собирать_манифесты.txt`** в этом каталоге.

## Манифесты лаунчера / модпака

| Скрипт | Описание |
|--------|----------|
| `generate_launcher_manifest.py` | Собирает манифест пака лаунчера (`manifest.json` / `<slug>.json`) из `pack_root` сервера. Читает `game_servers` из БД. Классифицирует моды (опциональные / обязательные-скрытые / только-серверные), ставит `alwaysOverwrite` изменяемым конфигам fancymenu и `managed` статичным медиа fancymenu (синк по хешу — обновления доходят до клиентов, а неизменные ассеты не перекачиваются). Клиентский профиль NeoForge выводится из версии сервера или из карты `CLIENT_PROFILE_NEOFORGE` (у voidrp клиент на 21.1.233 при сервере 21.1.232). Режимы: `--all` / `--server-slug <slug>`; legacy без флагов читает `/home/mironoouv/launcher/pack/`. |
| `generate_launcher_manifest.ps1` | Исходная PowerShell-версия (Windows). Поддерживаемая — это `.py`; логику матчинга (`OPTIONAL_MODS`, `REQUIRED_LOCKED_MODS`, `SERVER_ONLY_MODS`) держать синхронной. |
| `generate_runtime_manifest.py` | Собирает per-platform манифест Java-рантайма (runtime-seed) для бутстрапа рантайма в лаунчере. Читает `/home/mironoouv/launcher/runtime-seed/`. |
| `generate_abyss_manifests.sh` | Обёртка, пересобирающая манифесты сервера **VoidRP: Abyss** (Minecraft 26.2, NeoForge 26.2.0.8-beta) в его каталог `v26-abyss/manifests/`. |
| `generate_mods_list.py` | Сканирует `mods/` пака и отдаёт JSON-список модов (id, name, description, version) для вкладки «Моды» в гайде на сайте. Читает у каждого jar `META-INF/neoforge.mods.toml` (или legacy `mods.toml`). |

## Выгрузка данных для сайта (иконки / названия / рецепты)

| Скрипт | Описание |
|--------|----------|
| `build_item_names.py` | Извлекает `ru_ru.json` из всех модов → `item_names.json` для сайта. Также обновляет KubeJS-текстуры. |
| `extract_item_textures.py` | Извлекает текстуры предметов из jar-ов модов → `VOIDRP-SITE/public/item-icons/{modid}/{name}.png`. |
| `fetch_missing_icons.py` | Ищет и копирует недостающие иконки предметов из jar-ов (item texture → block texture → fuzzy-совпадение по имени). |
| `parse_recipes.py` | Парсит все KubeJS-рецепты из `server_scripts/` → `recipes.json` для сайта. |

## Маркеры карты (BlueMap / Dynmap)

| Скрипт | Описание |
|--------|----------|
| `update_bluemap_wg_markers.py` | Читает регионы WorldGuard, пишет их как маркеры BlueMap и красит каждый регион в акцентный цвет нации (берёт из API VoidRP). |
| `bluemap_markers_daemon.py` | Демон: следит за `live/markers.json` и мгновенно переинжектит регионы WorldGuard из `wg-regions.json` (задержка ≤ 0.5 с). |
| `update_dynmap_nation_colors.py` | Обновляет конфиг ownerstyle Dynmap-WorldGuard, чтобы регионы игрока красились в цвет его нации. |

## Жизненный цикл сервера / вотчдог

| Скрипт | Описание |
|--------|----------|
| `minecraft_watchdog.sh` | Вотчдог сервера: ловит зависания/краши, собирает диагностику, вызывает Claude. Заметки — в `watchdog.txt`. |
| `scheduled_restart.sh` | Плановый перезапуск сервера, по крону в 04:00. |
| `watchdog_logrotate.sh` | Архивирует `watchdog.log` и чистит старые архивы (каждые 12 ч). |
| `watchdog.txt` | Заметки / справка по конфигу вотчдога. |
