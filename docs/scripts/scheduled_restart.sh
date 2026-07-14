#!/usr/bin/env bash
# Плановый перезапуск сервера — запускается по крону в 04:00
set -uo pipefail

SERVER_DIR="/home/mironoouv/minecraft/minecraft_server"
RCON_HOST="127.0.0.1"
RCON_PORT="25575"
RCON_PASS_FILE="$SERVER_DIR/rcon.password"
LOG_FILE="/home/mironoouv/minecraft/scripts/watchdog.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] RESTART | $*" | tee -a "$LOG_FILE"
}

rcon() {
    local RP
    RP=$(cat "$RCON_PASS_FILE" 2>/dev/null || true)
    [[ -z "${RP:-}" ]] && return 1
    timeout 10 mcrcon -H "$RCON_HOST" -P "$RCON_PORT" -p "$RP" "$@" 2>/dev/null || true
}

if ! systemctl is-active youer --quiet 2>/dev/null; then
    log "сервер не запущен — плановый рестарт пропущен"
    exit 0
fi

log "плановый рестарт начат"
rcon "say §e[VoidRP] Плановый перезапуск сервера через 60 секунд. Сохраните прогресс!"
sleep 30
rcon "say §e[VoidRP] Перезапуск через 30 секунд..."
sleep 20
rcon "say §c[VoidRP] Перезапуск через 10 секунд!"
sleep 10
rcon "save-all flush" || true
sleep 3
rcon "stop" || true

# Ждём остановки (до 60 с), потом systemd сам поднимет
for i in $(seq 1 12); do
    sleep 5
    if ! systemctl is-active youer --quiet 2>/dev/null; then
        log "сервер остановлен (${i}x5s), ждём автозапуска systemd"
        break
    fi
done

log "плановый рестарт завершён"
