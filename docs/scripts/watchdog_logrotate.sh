#!/usr/bin/env bash
# Архивирует watchdog.log и удаляет старые архивы (запускается каждые 12 часов)

LOG_FILE="/home/mironoouv/minecraft/scripts/watchdog.log"
ARCHIVE_DIR="/home/mironoouv/minecraft/scripts/watchdog_logs"
MAX_ARCHIVES=28  # 14 дней × 2 архива в день

mkdir -p "$ARCHIVE_DIR"

# Архивируем только если лог не пустой
if [[ -s "$LOG_FILE" ]]; then
    ARCHIVE="$ARCHIVE_DIR/watchdog-$(date '+%Y-%m-%d_%H-%M').log.gz"
    gzip -c "$LOG_FILE" > "$ARCHIVE"
    # Очищаем лог, сохраняя файл с правильными правами
    > "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Log rotated → $(basename "$ARCHIVE")" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Archives kept: $(ls "$ARCHIVE_DIR"/*.log.gz 2>/dev/null | wc -l)" >> "$LOG_FILE"
fi

# Удаляем архивы старше MAX_ARCHIVES (оставляем только последние)
ls -t "$ARCHIVE_DIR"/*.log.gz 2>/dev/null | tail -n +$((MAX_ARCHIVES + 1)) | xargs -r rm -f