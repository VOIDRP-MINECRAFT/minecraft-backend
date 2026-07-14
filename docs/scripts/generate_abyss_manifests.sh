#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
# Генерация манифестов для VoidRP: Abyss (Minecraft 26.2, NeoForge 26.2.0.8-beta).
#
# Читает:  /home/mironoouv/launcher/v26-abyss/pack          (файлы модпака)
#          /home/mironoouv/launcher/v26-abyss/runtime-seed  (Java 25 + версии/либы клиента)
# Пишет:   /home/mironoouv/launcher/v26-abyss/manifests/abyss.json
#          /home/mironoouv/launcher/v26-abyss/manifests/runtime-manifest.win-x64.json
#          /home/mironoouv/launcher/v26-abyss/manifests/runtime-seed.json
#
# Использование:
#   ./generate_abyss_manifests.sh                 # pack-version = 1.0.0
#   PACK_VERSION=1.0.1 ./generate_abyss_manifests.sh
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ABYSS=/home/mironoouv/launcher/v26-abyss
BASE_URL=https://void-rp.ru/launcher/v26-abyss

MC_VERSION=26.2
NEOFORGE=26.2.0.8-beta
PROFILE_ID=neoforge-26.2.0.8-beta
FML=11.0.13
JAVA=25
HOST=void-rp.ru
PORT=25569

echo "── Манифест модпака ──────────────────────────────────────────"
python3 "$SCRIPTS_DIR/generate_launcher_manifest.py" \
  --pack-root "$ABYSS/pack" \
  --output "$ABYSS/manifests/abyss.json" \
  --base-url "$BASE_URL/pack" \
  --pack-name "VoidRP: Abyss" \
  --pack-version "${PACK_VERSION:-1.0.0}" \
  --pack-display-version "VoidRP Abyss $MC_VERSION" \
  --mc-version "$MC_VERSION" \
  --neoforge-version "$NEOFORGE" \
  --launcher-profile-id "$PROFILE_ID" \
  --fml-version "$FML" \
  --neoform-version "$MC_VERSION" \
  --java-version "$JAVA" \
  --server-host "$HOST" \
  --server-port "$PORT"

echo "── Runtime-манифест (Java 25 + клиентские файлы) ─────────────"
python3 "$SCRIPTS_DIR/generate_runtime_manifest.py" \
  --seed-root "$ABYSS/runtime-seed" \
  --output "$ABYSS/manifests/runtime-manifest.win-x64.json" \
  --base-url "$BASE_URL/runtime-seed" \
  --pack-name "VoidRP Abyss Runtime Seed" \
  --pack-display-version "VoidRP Abyss $MC_VERSION" \
  --launcher-profile-id "$PROFILE_ID" \
  --neoforge-version "$NEOFORGE" \
  --fml-version "$FML" \
  --neoform-version "$MC_VERSION" \
  --mc-version "$MC_VERSION" \
  --java-version "$JAVA" \
  --server-host "$HOST" \
  --server-port "$PORT"

echo "── runtime-seed.json (указатель на runtime-манифест) ─────────"
cat > "$ABYSS/manifests/runtime-seed.json" <<EOF
{ "manifestUrl": "$BASE_URL/manifests/runtime-manifest.win-x64.json" }
EOF

echo
echo "Готово. Файлы:"
ls -la "$ABYSS/manifests/"
