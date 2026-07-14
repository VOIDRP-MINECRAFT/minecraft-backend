#!/usr/bin/env bash
# Minecraft server watchdog — обнаруживает проблемы, собирает диагностику, вызывает Claude
set -uo pipefail

# ── Пути ──────────────────────────────────────────────────────────────────────
SERVER_DIR="/home/mironoouv/minecraft/minecraft_server"
PROJECT_DIR="/home/mironoouv/minecraft"
MAINTENANCE_FLAG="$SERVER_DIR/maintenance.flag"
LOCK_FILE="/tmp/mc_claude_watchdog.lock"
LOG_FILE="/home/mironoouv/minecraft/scripts/watchdog.log"
FAIL_COUNT_FILE="/tmp/mc_claude_fail_count"
LOG_POS_FILE="/tmp/mc_watchdog_logpos"
LOG_INODE_FILE="/tmp/mc_watchdog_log_inode"
SPARK_CONSEC_FILE="/tmp/mc_watchdog_spark_consec"
HUNG_SHUTDOWN_SINCE_FILE="/tmp/mc_hung_shutdown_since"
BOOT_CRASH_LOOP_FILE="/tmp/mc_boot_crash_loop"   # timestamps of recent boot crashes
BOOT_CRASH_LOOP_WINDOW=300   # seconds — N crashes in this window = restart loop
BOOT_CRASH_LOOP_THRESHOLD=2  # consecutive boot crashes before maintenance mode
BOOT_CRASH_MIN_UPTIME=120    # server uptime < this (s) = considered a boot crash
MAX_ATTEMPTS=3

# ── Пороги ────────────────────────────────────────────────────────────────────
STARTUP_GRACE=300           # секунд после старта перед проверкой порта
SPARK_CONSEC_THRESHOLD=10   # N итераций подряд со Spark таймаутами → SPARK_TIMEOUT_STORM
CANT_KEEP_THRESHOLD=5       # N "Can't keep up!" в одной пачке → предупреждение в логе

# ── RCON (опционально, для TPS в диагностике) ─────────────────────────────────
RCON_HOST="127.0.0.1"
RCON_PORT="25575"
RCON_PASS_FILE="$SERVER_DIR/rcon.password"   # файл с одной строкой — паролем

# ── Временный файл новых строк лога (живёт только в рамках одного запуска) ────
NEW_LINES_FILE="/tmp/mc_newlines_$$.tmp"
cleanup() { rm -f "$NEW_LINES_FILE"; }
trap cleanup EXIT

# ── Флаги режима запуска ───────────────────────────────────────────────────────
# ./minecraft_watchdog.sh --improve    → только самоулучшение (для cron/ручного запуска)
RUN_MODE="${1:-watch}"

# Устанавливаются в detect_pattern()
PATTERN_TYPE=""
PATTERN_CTX=""

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ──────────────────────────────────────────────────────────────────────────────
# snapshot_new_log_lines
# Читает новые строки latest.log с момента прошлой проверки,
# пишет в NEW_LINES_FILE. Обновляет позицию (inode + line count).
# Возвращает 0 если есть новые строки, 1 если нет.
# ──────────────────────────────────────────────────────────────────────────────
snapshot_new_log_lines() {
    local LOG_MC="$SERVER_DIR/logs/latest.log"
    > "$NEW_LINES_FILE"
    [[ -f "$LOG_MC" ]] || return 1

    local CUR_INODE CUR_LINES
    CUR_INODE=$(stat -c %i "$LOG_MC" 2>/dev/null || echo 0)
    CUR_LINES=$(wc -l < "$LOG_MC" 2>/dev/null || echo 0)

    local LAST_INODE LAST_POS
    LAST_INODE=$(cat "$LOG_INODE_FILE" 2>/dev/null || echo 0)
    LAST_POS=$(cat "$LOG_POS_FILE"    2>/dev/null || echo 0)

    # Новый файл (сервер перезапустился, log ротировался) — сброс fail count
    if [[ "$CUR_INODE" != "$LAST_INODE" ]]; then
        LAST_POS=0
        echo 0 > "$FAIL_COUNT_FILE"
    fi

    echo "$CUR_INODE" > "$LOG_INODE_FILE"
    echo "$CUR_LINES" > "$LOG_POS_FILE"

    (( CUR_LINES <= LAST_POS )) && return 1
    sed -n "$((LAST_POS + 1)),${CUR_LINES}p" "$LOG_MC" 2>/dev/null > "$NEW_LINES_FILE"
    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# detect_pattern
# Анализирует NEW_LINES_FILE. Устанавливает PATTERN_TYPE и PATTERN_CTX.
# Приоритет: OOM > HUNG_TICK > SPARK_STORM > CANT_KEEP (только лог, не триггер)
# ──────────────────────────────────────────────────────────────────────────────
detect_pattern() {
    PATTERN_TYPE=""
    PATTERN_CTX=""

    if [[ ! -s "$NEW_LINES_FILE" ]]; then
        echo 0 > "$SPARK_CONSEC_FILE"
        return 0
    fi

    # 1a. FATAL mixin error — server cannot start, needs code fix (not a restart)
    local MIXIN_FATAL_LINE
    MIXIN_FATAL_LINE=$(grep -m1 "\[main/FATAL\].*mixin\|InvalidMixinException\|Mixin prepare.*failed" "$NEW_LINES_FILE" 2>/dev/null || true)
    if [[ -n "$MIXIN_FATAL_LINE" ]]; then
        local MIXIN_CTX
        MIXIN_CTX=$(grep -E "\[main/FATAL\].*mixin|InvalidMixinException|Mixin prepare.*failed|target type mismatch" "$NEW_LINES_FILE" 2>/dev/null | head -5 | tr '\n' ' ')
        PATTERN_TYPE="MIXIN_FATAL"
        PATTERN_CTX="Mixin FATAL при загрузке: $MIXIN_CTX"
        echo 0 > "$SPARK_CONSEC_FILE"
        return 0
    fi

    # 1b. OutOfMemoryError — наивысший приоритет, может появиться до краша
    if grep -q "java\.lang\.OutOfMemoryError" "$NEW_LINES_FILE" 2>/dev/null; then
        local OOM_LINE
        OOM_LINE=$(grep -m1 "java\.lang\.OutOfMemoryError" "$NEW_LINES_FILE")
        PATTERN_TYPE="OOM"
        PATTERN_CTX="OutOfMemoryError в логе: $OOM_LINE"
        echo 0 > "$SPARK_CONSEC_FILE"
        return 0
    fi

    # 2. Minecraft Watchdog thread dump ("server has not responded for N seconds")
    local DUMP_LINE_N
    DUMP_LINE_N=$(grep -n "has not responded for" "$NEW_LINES_FILE" 2>/dev/null | tail -1 | cut -d: -f1)
    if [[ -n "$DUMP_LINE_N" ]]; then
        # Извлекаем thread dump (~80 строк) прямо сейчас, пока файл доступен
        local DUMP_EXCERPT
        DUMP_EXCERPT=$(sed -n "${DUMP_LINE_N},$((DUMP_LINE_N + 80))p" "$NEW_LINES_FILE" 2>/dev/null)

        # Пре-диагноз по известным фреймам стека
        local SIGNALS=""
        echo "$DUMP_EXCERPT" | grep -q "LockSupport\.park"          && SIGNALS+=" [DEADLOCK:LockSupport.park]"
        echo "$DUMP_EXCERPT" | grep -q "citizensnpcs\|EventListen"  && SIGNALS+=" [CITIZENS]"
        echo "$DUMP_EXCERPT" | grep -q "CraftChunk\.getEntities"     && SIGNALS+=" [CRAFTCHUNK_GETENTITIES]"
        # CHUNK_LOAD_DEADLOCK: ServerChunkCache присутствует И есть реальный блок потока
        if echo "$DUMP_EXCERPT" | grep -q "ServerChunkCache" && \
           echo "$DUMP_EXCERPT" | grep -qE "managedBlock|LockSupport\.park"; then
            SIGNALS+=" [CHUNK_LOAD_DEADLOCK]"
        fi
        echo "$DUMP_EXCERPT" | grep -q "DistanceManager"             && SIGNALS+=" [DISTANCE_MANAGER]"
        echo "$DUMP_EXCERPT" | grep -q "postProcessFluid\|FluidState" && SIGNALS+=" [FLUID_TICK]"
        echo "$DUMP_EXCERPT" | grep -q "StackOverflowError"          && SIGNALS+=" [STACK_OVERFLOW]"
        # BLOCK_COLLISION_CHUNK: BlockCollisions присутствует И поток реально заблокирован
        if echo "$DUMP_EXCERPT" | grep -q "BlockCollisions" && \
           echo "$DUMP_EXCERPT" | grep -qE "managedBlock|parkNanos|LockSupport\.park"; then
            SIGNALS+=" [BLOCK_COLLISION_CHUNK]"
        fi

        PATTERN_TYPE="HUNG_TICK"
        PATTERN_CTX="Thread dump на строке ~$DUMP_LINE_N в новой пачке.${SIGNALS:+ Паттерны: $SIGNALS}"
        echo 0 > "$SPARK_CONSEC_FILE"
        return 0
    fi

    # 3. Spark timeout storm
    local SPARK_COUNT
    SPARK_COUNT=$(grep -c "Timed out waiting for world statistics" "$NEW_LINES_FILE" 2>/dev/null || true)
    if (( SPARK_COUNT > 0 )); then
        local CONSEC
        CONSEC=$(cat "$SPARK_CONSEC_FILE" 2>/dev/null || echo 0)
        CONSEC=$(( CONSEC + 1 ))
        echo "$CONSEC" > "$SPARK_CONSEC_FILE"

        if (( CONSEC >= SPARK_CONSEC_THRESHOLD )); then
            # Несколько строк прямо перед первым таймаутом — там причина лага
            local FIRST_SPARK LINES_BEFORE=""
            FIRST_SPARK=$(grep -n "Timed out waiting for world statistics" "$NEW_LINES_FILE" | head -1 | cut -d: -f1)
            if [[ -n "$FIRST_SPARK" ]] && (( FIRST_SPARK > 3 )); then
                LINES_BEFORE=$(sed -n "$((FIRST_SPARK - 3)),$((FIRST_SPARK - 1))p" "$NEW_LINES_FILE" 2>/dev/null)
            fi
            PATTERN_TYPE="SPARK_STORM"
            PATTERN_CTX="${CONSEC} итераций подряд (${SPARK_COUNT} в пачке). Строки перед первым таймаутом: [$LINES_BEFORE]"
            echo 0 > "$SPARK_CONSEC_FILE"   # сбрасываем после триггера
        else
            log "SPARK | ${CONSEC}/${SPARK_CONSEC_THRESHOLD} итераций (${SPARK_COUNT} в пачке) — жду порога"
        fi
        return 0
    else
        echo 0 > "$SPARK_CONSEC_FILE"
    fi

    # 4. "Can't keep up!" flood — не запускаем Claude, только логируем предупреждение
    local CKU_COUNT
    CKU_COUNT=$(grep -c "Can't keep up!" "$NEW_LINES_FILE" 2>/dev/null || true)
    if (( CKU_COUNT >= CANT_KEEP_THRESHOLD )); then
        log "WARN | TPS проблема: ${CKU_COUNT}x 'Can't keep up!' в пачке — мониторю"
    fi

    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# gather_diagnostics SCENARIO
# Собирает диагностический снепшот в /tmp/mc_diag_<scenario>_<ts>.txt.
# Включает: память JVM, диск, TPS (RCON), известные паттерны,
#           новые строки лога, последние 150 строк.
# Выводит путь к файлу.
# ──────────────────────────────────────────────────────────────────────────────
gather_diagnostics() {
    local SCENARIO="$1"
    local DIAG_FILE="/tmp/mc_diag_${SCENARIO}_$(date +%s).txt"

    {
        echo "╔══ VoidRP Watchdog · Diagnostic Snapshot ════════════════════════╗"
        printf "  Сценарий : %s\n" "$SCENARIO"
        printf "  Время    : %s\n" "$(date)"
        echo "╚═════════════════════════════════════════════════════════════════╝"
        echo ""

        # ── JVM процесс ──────────────────────────────────────────────────────
        echo "─── JVM процесс ──────────────────────────────────────────────────"
        local JVM_PID
        JVM_PID=$(pgrep -f "youer\.jar" 2>/dev/null | head -1 || true)
        if [[ -n "${JVM_PID:-}" ]]; then
            echo "PID: $JVM_PID"
            grep -E '^(VmRSS|VmPeak|VmSwap|Threads):' "/proc/$JVM_PID/status" 2>/dev/null \
                || echo "(нет данных /proc)"
            # Суммарное CPU время (user + sys)
            local CPU_TICKS
            CPU_TICKS=$(awk '{print $14+$15}' "/proc/$JVM_PID/stat" 2>/dev/null || echo "?")
            [[ "$CPU_TICKS" != "?" ]] && echo "CPU ticks (user+sys): $CPU_TICKS / $(getconf CLK_TCK)/s"
        else
            echo "youer.jar — процесс не найден"
        fi
        echo ""

        # ── Диск ─────────────────────────────────────────────────────────────
        echo "─── Диск ────────────────────────────────────────────────────────"
        df -h "$SERVER_DIR" 2>/dev/null | tail -1 || echo "(нет данных)"
        echo ""

        # ── Игроки онлайн ─────────────────────────────────────────────────────
        echo "─── Игроки онлайн ───────────────────────────────────────────────"
        local PLAYER_CONN
        PLAYER_CONN=$(ss -tn state established 2>/dev/null | grep -c ":25565 " || echo 0)
        echo "Активных TCP соединений на :25565 = $PLAYER_CONN"
        echo "(0 = нет игроков; >0 = игроки подключены)"
        echo ""

        # ── TPS (RCON) ────────────────────────────────────────────────────────
        echo "─── TPS (RCON) ──────────────────────────────────────────────────"
        if command -v mcrcon &>/dev/null && [[ -f "$RCON_PASS_FILE" ]]; then
            local RP
            RP=$(cat "$RCON_PASS_FILE" 2>/dev/null || true)
            if [[ -n "${RP:-}" ]]; then
                timeout 6 mcrcon -H "$RCON_HOST" -P "$RCON_PORT" -p "$RP" "tps" 2>&1 \
                    || echo "RCON — таймаут / недоступен"
            else
                echo "RCON пароль пуст в $RCON_PASS_FILE"
            fi
        else
            echo "(mcrcon не установлен или $RCON_PASS_FILE не существует — пропускаю)"
        fi
        echo ""

        # ── Сигналы в последних 300 строках лога ─────────────────────────────
        echo "─── Сигналы (последние 300 строк лога) ──────────────────────────"
        local TAIL300
        TAIL300=$(tail -300 "$SERVER_DIR/logs/latest.log" 2>/dev/null || true)
        if [[ -n "$TAIL300" ]]; then
            printf "  OutOfMemoryError         : %d\n" "$(echo "$TAIL300" | grep -c "OutOfMemoryError"      2>/dev/null || echo 0)"
            printf "  Can't keep up!           : %d\n" "$(echo "$TAIL300" | grep -c "Can't keep up!"        2>/dev/null || echo 0)"
            printf "  Exception/Error строк    : %d\n" "$(echo "$TAIL300" | grep -cE "(Exception|Error):"   2>/dev/null || echo 0)"
            printf "  Spark таймаутов          : %d\n" "$(echo "$TAIL300" | grep -c "Timed out waiting"     2>/dev/null || echo 0)"
            printf "  has not responded        : %d\n" "$(echo "$TAIL300" | grep -c "has not responded for" 2>/dev/null || echo 0)"
            echo ""
            # Специфические паттерны — выводим предупреждение если нашли
            echo "$TAIL300" | grep -q "LockSupport\.parkNanos"  && echo "  ⚠  DEADLOCK: LockSupport.parkNanos обнаружен"
            echo "$TAIL300" | grep -q "StackOverflowError"      && echo "  ⚠  StackOverflowError"
            echo "$TAIL300" | grep -q "not belonging to us"     && echo "  ⚠  Mohist: chunk not belonging to us"
            echo "$TAIL300" | grep -q "CraftChunk.*getEntities" && echo "  ⚠  Citizens: CraftChunk.getEntities deadlock"
            echo "$TAIL300" | grep -q "java\.lang\.Thread\.State: BLOCKED" && echo "  ⚠  Thread BLOCKED (deadlock вероятен)"
            true
        else
            echo "  (лог недоступен)"
        fi
        echo ""

        # ── Новые строки с прошлой проверки (сам триггер) ────────────────────
        echo "─── Новые строки лога с прошлой проверки ────────────────────────"
        if [[ -s "$NEW_LINES_FILE" ]]; then
            local NL_COUNT
            NL_COUNT=$(wc -l < "$NEW_LINES_FILE" 2>/dev/null || echo 0)
            echo "(${NL_COUNT} строк; показываю не более 400)"
            echo "---"
            if (( NL_COUNT > 400 )); then
                echo "[...первые $((NL_COUNT - 400)) строк скрыты...]"
                tail -400 "$NEW_LINES_FILE"
            else
                cat "$NEW_LINES_FILE"
            fi
        else
            echo "(нет новых строк)"
        fi
        echo ""

        # ── Последние 150 строк лога — финальный контекст ────────────────────
        echo "─── Последние 150 строк latest.log ──────────────────────────────"
        tail -150 "$SERVER_DIR/logs/latest.log" 2>/dev/null || echo "(лог недоступен)"

    } > "$DIAG_FILE" 2>&1

    echo "$DIAG_FILE"
}

# ──────────────────────────────────────────────────────────────────────────────
# launch_claude SCENARIO EXTRA_CTX
# ──────────────────────────────────────────────────────────────────────────────
launch_claude() {
    local SCENARIO="$1"
    local EXTRA_CTX="$2"

    # Один экземпляр одновременно
    if [[ -f "$LOCK_FILE" ]]; then
        local PID
        PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
        if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
            log "CLAUDE | уже запущен (PID $PID) — пропускаю"
            return
        fi
        # Убиваем зависший claude/timeout если вдруг жив без lock
        pkill -TERM -f "timeout 600 claude" 2>/dev/null || true
        sleep 1
        pkill -KILL -f "timeout 600 claude" 2>/dev/null || true
        log "CLAUDE | устаревший lock удалён (PID ${PID:-?} мёртв)"
        rm -f "$LOCK_FILE"
    fi

    local FAIL_COUNT
    FAIL_COUNT=$(cat "$FAIL_COUNT_FILE" 2>/dev/null || echo 0)
    if (( FAIL_COUNT >= MAX_ATTEMPTS )); then
        log "CLAUDE | попытки исчерпаны ($MAX_ATTEMPTS) — нужно ручное вмешательство"
        return
    fi
    echo $((FAIL_COUNT + 1)) > "$FAIL_COUNT_FILE"

    # Собираем диагностику ДО запуска Claude
    log "CLAUDE | собираю диагностический снепшот..."
    local DIAG_FILE
    DIAG_FILE=$(gather_diagnostics "$SCENARIO")
    log "CLAUDE | снепшот готов: $DIAG_FILE"

    # Последний crash report
    local CRASH_HINT="Crash reports отсутствуют."
    local CRASH_REPORT
    CRASH_REPORT=$(ls -t "$SERVER_DIR/crash-reports/"*.txt 2>/dev/null | head -1 || true)
    if [[ -n "$CRASH_REPORT" ]]; then
        local REPORT_AGE
        REPORT_AGE=$(( $(date +%s) - $(stat -c %Y "$CRASH_REPORT" 2>/dev/null || echo 0) ))
        CRASH_HINT="Последний crash report: $CRASH_REPORT (возраст: $((REPORT_AGE / 60)) мин)"
    fi

    local SCENARIO_DESC TASK EXTRA_HINTS=""
    case "$SCENARIO" in
    MIXIN_FATAL)
        SCENARIO_DESC="упал при старте из-за ошибки Mixin (InvalidMixinException / target type mismatch)"
        TASK="1. Прочитай диагностический снепшот ПЕРВЫМ — там уже есть FATAL-строки с именем класса миксина и целевого класса.
2. Найди сломанный mixin-файл в /home/mironoouv/minecraft/voidrp_async_ai/src/main/java/ru/voidrp/asyncai/mixin/
3. Типичные причины:
   а) @Mixin нацелен на интерфейс вместо конкретного класса → переделай на @Redirect/@Inject в нужном конкретном классе
   б) Неверная сигнатура метода в @Inject target → исправь дескриптор
   в) Метод из интерфейса с default-реализацией → используй @Redirect на вызывающем классе, не на интерфейсе
4. Исправь mixin-файл:
   - Если цель — интерфейс: измени @Mixin на конкретный класс-реализатор и используй @Redirect на call-site
   - Если неверный target-дескриптор: исправь сигнатуру
5. Собери и задеплой:
     cd /home/mironoouv/minecraft/voidrp_async_ai
     ./gradlew build
     cp build/libs/voidrp_async_ai-1.0.0.jar ../minecraft_server/mods/voidrp_async_ai-1.0.0.jar
6. sudo systemctl reset-failed youer && sudo systemctl start youer
7. Подожди 90 с: systemctl is-active youer
8. Проверь что FATAL-строки исчезли из нового лога
9. Резюме: что именно было неверно и как исправлено"
        ;;
    HUNG_SHUTDOWN)
        SCENARIO_DESC="завис при shutdown: JVM жив (порт 25565 не слушает)"
        local STOP_LINE
        STOP_LINE=$(grep -n "Stopping server" "$SERVER_DIR/logs/latest.log" 2>/dev/null | tail -1 | cut -d: -f1 || true)
        [[ -n "$STOP_LINE" ]] \
            && EXTRA_HINTS="'Stopping server' в latest.log: строка ~${STOP_LINE} — читай ~100 строк ДО неё." \
            || EXTRA_HINTS="'Stopping server' в latest.log не найдена — проверь конец файла."
        TASK="1. Прочитай диагностический снепшот ПЕРВЫМ (путь ниже).
2. Затем прочитай latest.log вокруг 'Stopping server' (~100 строк до). Определи триггер.
3. Найди корневую причину (проблемный мод, зависший тик, битый чанк/NBT, утечка памяти).
4. Примени фикс если возможно.
5. Убей зависший JVM и перезапусти:
     sudo systemctl kill -s SIGKILL youer && sleep 3
     sudo systemctl reset-failed youer && sudo systemctl start youer
6. Подожди 60 с, проверь: systemctl is-active youer
7. Резюме: причина + что починено (или почему нельзя — тогда НЕ запускай)"
        ;;
    HUNG_TICK)
        SCENARIO_DESC="главный поток завис (Minecraft Watchdog напечатал thread dump)"
        TASK="1. Прочитай диагностический снепшот ПЕРВЫМ — там уже есть thread dump, пре-диагноз по фреймам стека, счётчики ошибок, количество игроков онлайн.
2. Определи что застряло: entity, мод, блок, команда.
3. ИГРОКИ: в снепшоте есть «Активных TCP соединений на :25565». Если > 0 — игроки подключены.
   - Приоритет: найди и примени фикс БЕЗ рестарта (mixin/конфиг/killEntity через RCON).
   - Если фикс без рестарта невозможен или TPS=0 — рестарт неизбежен, выполни его.
   - Если игроков нет — рестарт сразу без колебаний.
4. Проверь порт: ss -tnl | grep ':25565'
   а) Слушает (сервер завис но живой) → sudo systemctl kill -s SIGKILL youer && sleep 3
   б) Не слушает (уже упал) → перейди к фиксу
5. Типичные фиксы:
   - voidrp_async_ai mixin (guard / early-return / лимит итераций)
   - Entity в цикле коллизий: найди по типу в NBT, перемести регион-файл
   - Правка конфига мода
6. sudo systemctl reset-failed youer && sudo systemctl start youer
7. Подожди 60 с: systemctl is-active youer
8. Резюме"
        ;;
    SPARK_TIMEOUT_STORM)
        SCENARIO_DESC="главный поток лагает: Spark непрерывно таймаутит"
        TASK="1. Прочитай диагностический снепшот ПЕРВЫМ — там TPS (RCON), строки ДО первого таймаута, счётчики, количество игроков онлайн.
2. Найди причину лага по строкам перед первым Spark таймаутом.
3. ИГРОКИ: в снепшоте есть «Активных TCP соединений на :25565».
   - Если игроки онлайн — сервер жив и они лагают, но ещё подключены.
   - СНАЧАЛА попробуй фикс без рестарта: voidrp_async_ai mixin, /kill @e[type=!player] через RCON, отключить WorldEdit операцию и т.п.
   - Рестарт только если TPS < 5 и фикс без рестарта невозможен или не помог.
   - Если игроков нет — рестарт сразу.
4. TPS через RCON (дополнительно к снепшоту):
     mcrcon -H 127.0.0.1 -P 25575 'tps'   (дай 15 с при сильном лаге)
5. Определи источник: entity AI overflow, chunk-loading, редстоун, WorldEdit, мод.
6. Примени фикс (предпочтительно voidrp_async_ai mixin).
7. Если рестарт нужен:
     sudo systemctl kill -s SIGKILL youer && sleep 3
     sudo systemctl reset-failed youer && sudo systemctl start youer
8. Подожди 60 с: systemctl is-active youer
9. Резюме"
        ;;
    *)  # CRASH + OOM
        SCENARIO_DESC="упал или OOM (systemd исчерпал попытки / OutOfMemoryError в логе)"
        TASK="1. Прочитай диагностический снепшот ПЕРВЫМ — там счётчики ошибок, новые строки лога (с самим OOM/краш-строкой), последние 150 строк.
2. Прочитай crash report (путь в снепшоте).
3. Определи точную причину. Если OOM — что потребляет память (entity overhead, кэш мода, утечка).
4. Примени минимальный фикс.
5. sudo systemctl reset-failed youer && sudo systemctl start youer
6. Подожди 30 с: systemctl is-active youer
7. Резюме: причина + что починено (или почему нельзя — тогда НЕ запускай)"
        ;;
    esac

    local PROMPT
    PROMPT="Майнкрафт сервер (NeoForge 1.21.1 / Mohist, Youer) $SCENARIO_DESC.
Ты запущен ватчдогом автоматически для диагностики и починки.

Сценарий : $SCENARIO
Попытка  : $((FAIL_COUNT + 1)) из $MAX_ATTEMPTS
Время    : $(date)
$EXTRA_CTX

╔══ НАЧНИ ЗДЕСЬ — ДИАГНОСТИЧЕСКИЙ СНЕПШОТ ══════════════════════════════╗
  Прочитай файл ПЕРВЫМ: $DIAG_FILE
  Он содержит: память JVM · TPS (RCON) · счётчики ошибок ·
               новые строки лога с прошлой проверки (там сам триггер) ·
               последние 150 строк latest.log.
  Это даёт мгновенный контекст и позволяет сразу понять причину.
╚════════════════════════════════════════════════════════════════════════╝

Лог сервера : $SERVER_DIR/logs/latest.log
$EXTRA_HINTS
$CRASH_HINT

=== ЗАДАЧА ===
$TASK

=== ЧТО МОЖНО ДЕЛАТЬ ===
ПРЕДПОЧТИТЕЛЬНЫЙ способ фикса — доработать voidrp_async_ai и задеплоить:
  Мод     : /home/mironoouv/minecraft/voidrp_async_ai
  Миксины : src/main/java/ru/voidrp/asyncai/mixin/
  Уже есть: EntityCollisionGuardMixin, NavigationThrottleMixin,
            EntityHibernateMixin, BrainThrottleMixin,
            CitizensChunkUnloadGuardMixin и др.
  Сборка и деплой:
    cd /home/mironoouv/minecraft/voidrp_async_ai
    ./gradlew build
    cp build/libs/voidrp_async_ai-1.0.0.jar ../minecraft_server/mods/voidrp_async_ai-1.0.0.jar
  Используй если проблему решает mixin (guard, early-return, лимит итераций, offload).

Остальные допустимые действия:
- Байткод-патч JAR чужих модов (ASM)
- Редактировать конфиги модов (config/*.toml, config/*.json)
- Перемещать/переименовывать битые NBT / регион-файлы — только если явная причина
- Читать логи, crash report, NBT для диагностики

=== КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО ===
- Удалять JAR-файлы модов (mods/*.jar) — рассинхрон с клиентами
- Скачивать или заменять моды на новые версии
- Удалять данные игроков (world/playerdata/, world/stats/, world/advancements/)
- Удалять мировые данные (world/region/, world/DIM-1/, world/DIM1/)
- Удалять плагины (plugins/*.jar)
- Менять версию сервера (youer.jar)
- Трогать файлы аутентификации и безопасности"

    log "CLAUDE | запускаю scenario=$SCENARIO попытка=$((FAIL_COUNT + 1))/$MAX_ATTEMPTS"

    export HTTP_PROXY=http://127.0.0.1:8118
    export HTTPS_PROXY=http://127.0.0.1:8118
    export HOME=/home/mironoouv
    export PATH="/home/mironoouv/.local/bin:/usr/local/bin:/usr/bin:/bin"

    cd "$PROJECT_DIR"
    # Запускаем claude в фоне и сохраняем PID фонового subshell-а в lock.
    # Так при рестарте watchdog-сервиса старый claude остаётся живым и lock валиден.
    {
        echo "========== CLAUDE START $(date '+%Y-%m-%d %H:%M:%S') scenario=$SCENARIO =========="
        timeout 600 claude --dangerously-skip-permissions -p "$PROMPT" 2>&1
        echo "========== CLAUDE END $(date '+%Y-%m-%d %H:%M:%S') =========="
    } >> "$LOG_FILE" &
    local CLAUDE_BG=$!
    echo "$CLAUDE_BG" > "$LOCK_FILE"
    wait "$CLAUDE_BG"

    rm -f "$LOCK_FILE"
    log "CLAUDE | завершён"

    if systemctl is-active youer --quiet 2>/dev/null; then
        log "RESULT | УСПЕХ — сервер запущен (попытка $((FAIL_COUNT + 1)))"
        echo 0 > "$FAIL_COUNT_FILE"
        # После успешного фикса — запускаем самоулучшение в фоне
        launch_claude_self_improve "$SCENARIO" "$EXTRA_CTX" &
    else
        log "RESULT | НЕУДАЧА — сервер не запустился (попытка $((FAIL_COUNT + 1)))"
    fi
}

# ──────────────────────────────────────────────────────────────────────────────
# launch_claude_self_improve SCENARIO INCIDENT_CTX
# Отдельный агент-рефлексия: анализирует инцидент и улучшает сам watchdog.
# Запускается в фоне после успешного фикса или вручную через --improve.
# Полностью изолирован от Minecraft-промпта — работает только с watchdog.sh.
# ──────────────────────────────────────────────────────────────────────────────
launch_claude_self_improve() {
    local SCENARIO="${1:-manual}"
    local INCIDENT_CTX="${2:-}"
    local IMPROVE_LOCK="/tmp/mc_claude_improve.lock"
    local IMPROVE_LOG="$LOG_FILE"   # пишем в тот же лог, но с префиксом IMPROVE

    # Один экземпляр самоулучшения одновременно
    if [[ -f "$IMPROVE_LOCK" ]]; then
        local IPID
        IPID=$(cat "$IMPROVE_LOCK" 2>/dev/null || echo "")
        if [[ -n "$IPID" ]] && kill -0 "$IPID" 2>/dev/null; then
            log "IMPROVE | уже запущено (PID $IPID) — пропускаю"
            return
        fi
        rm -f "$IMPROVE_LOCK"
    fi

    log "IMPROVE | запускаю самоулучшение watchdog (инцидент: $SCENARIO)"
    echo "$BASHPID" > "$IMPROVE_LOCK"

    # Берём последние 60 строк watchdog.log (включая только что завершённый инцидент)
    local RECENT_LOG
    RECENT_LOG=$(tail -60 "$IMPROVE_LOG" 2>/dev/null || echo "(лог недоступен)")

    local IMPROVE_PROMPT
    IMPROVE_PROMPT="Ты — автоматический рефакторинг-агент watchdog-скрипта для Minecraft сервера VoidRP.

ТОЛЬКО ЧТО завершился инцидент:
  Сценарий      : $SCENARIO
  Доп. контекст : $INCIDENT_CTX

Скрипт watchdog: $0
Watchdog лог   : $IMPROVE_LOG

=== ЗАДАЧА ===
1. Прочитай текущий watchdog скрипт: $0
2. Прочитай последние строки watchdog.log (они ниже — это только что обработанный инцидент).
3. Проанализируй: можно ли улучшить watchdog чтобы в следующий раз:
   а) Обнаружить этот тип проблемы РАНЬШЕ (новые паттерны в detect_pattern)?
   б) Дать Claude более точный контекст (улучшить gather_diagnostics)?
   в) Написать более точный промпт для данного сценария (launch_claude)?
   г) Добавить новый сценарий если этот не покрывался корректно?
4. Если улучшение есть и оно нетривиально — внеси его в скрипт.
5. Если улучшений нет или инцидент обработан оптимально — ничего не меняй.

=== ОГРАНИЧЕНИЯ ===
- Меняй ТОЛЬКО файл: $0
- НЕ трогай промпт других сценариев если они к инциденту не относятся
- НЕ меняй механику запуска claude (переменные окружения, lock-файлы, флаг --dangerously-skip-permissions)
- Сохраняй структуру: snapshot_new_log_lines / detect_pattern / gather_diagnostics / launch_claude / launch_claude_self_improve / MAIN
- НЕ добавляй зависимости на внешние инструменты без проверки их наличия через command -v

=== ПОСЛЕДНИЕ СТРОКИ WATCHDOG.LOG (инцидент) ===
$RECENT_LOG

=== ВЫВОД ===
Напиши одним абзацем: что изменил и зачем, или почему ничего не менял."

    export HTTP_PROXY=http://127.0.0.1:8118
    export HTTPS_PROXY=http://127.0.0.1:8118
    export HOME=/home/mironoouv
    export PATH="/home/mironoouv/.local/bin:/usr/local/bin:/usr/bin:/bin"

    cd "$PROJECT_DIR"
    {
        echo "========== IMPROVE START $(date '+%Y-%m-%d %H:%M:%S') after=$SCENARIO =========="
        timeout 300 claude --dangerously-skip-permissions -p "$IMPROVE_PROMPT" 2>&1
        echo "========== IMPROVE END $(date '+%Y-%m-%d %H:%M:%S') =========="
    } >> "$IMPROVE_LOG"

    rm -f "$IMPROVE_LOCK"
    log "IMPROVE | завершено"
}

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

# Режим ручного самоулучшения: ./minecraft_watchdog.sh --improve
if [[ "$RUN_MODE" == "--improve" ]]; then
    log "IMPROVE | ручной запуск самоулучшения"
    launch_claude_self_improve "manual" "Ручной запуск оператором (не инцидент)"
    exit 0
fi

STATE=$(systemctl show youer --property=ActiveState --value 2>/dev/null || echo "unknown")
FAIL_COUNT=$(cat "$FAIL_COUNT_FILE" 2>/dev/null || echo 0)

log "CHECK | state=${STATE} | fail=${FAIL_COUNT}/${MAX_ATTEMPTS} | maintenance=$([ -f "$MAINTENANCE_FLAG" ] && echo yes || echo no)"

if [[ -f "$MAINTENANCE_FLAG" ]]; then
    log "STATUS | режим обслуживания — пропускаю"
    exit 0
fi

if systemctl is-active youer --quiet 2>/dev/null; then

    # Считаем uptime сервиса
    ACTIVE_MONO=$(systemctl show youer --property=ActiveEnterTimestampMonotonic --value 2>/dev/null | head -1 || echo 0)
    NOW_MONO=$(awk '{print int($1 * 1000000)}' /proc/uptime)
    UPTIME_SECS=999
    if [[ "${ACTIVE_MONO:-0}" =~ ^[0-9]+$ ]] && (( ACTIVE_MONO > 0 )); then
        UPTIME_SECS=$(( (NOW_MONO - ACTIVE_MONO) / 1000000 ))
    fi

    # Проверка HUNG_SHUTDOWN: JVM жив, но порт не слушает.
    # Grace-период 45 с — даём JVM время умереть самому при нормальном shutdown,
    # чтобы не запускать Claude зря на каждый плановый/чистый останов.
    if (( UPTIME_SECS > STARTUP_GRACE )) && ! ss -tnl 2>/dev/null | grep -q ':25565 '; then
        NOW_TS=$(date +%s)
        if [[ -f "$HUNG_SHUTDOWN_SINCE_FILE" ]]; then
            SINCE_TS=$(cat "$HUNG_SHUTDOWN_SINCE_FILE" 2>/dev/null || echo "$NOW_TS")
            ELAPSED_HS=$(( NOW_TS - SINCE_TS ))
            if (( ELAPSED_HS >= 45 )); then
                log "HUNG_SHUTDOWN | JVM жив (uptime ${UPTIME_SECS}s) но порт 25565 не слушает (grace ${ELAPSED_HS}s)"
                rm -f "$HUNG_SHUTDOWN_SINCE_FILE"
                snapshot_new_log_lines || true
                launch_claude "HUNG_SHUTDOWN" "Uptime сервиса до обнаружения зависания: ${UPTIME_SECS}s"
                exit 0
            else
                log "HUNG_SHUTDOWN | порт закрыт (uptime ${UPTIME_SECS}s) — grace ${ELAPSED_HS}/45s, жду..."
            fi
        else
            echo "$NOW_TS" > "$HUNG_SHUTDOWN_SINCE_FILE"
            log "HUNG_SHUTDOWN | порт закрыт (uptime ${UPTIME_SECS}s) — grace период начат"
        fi
        exit 0
    fi
    rm -f "$HUNG_SHUTDOWN_SINCE_FILE"

    # Сканируем новые строки лога на паттерны проблем
    if snapshot_new_log_lines; then
        detect_pattern

        case "$PATTERN_TYPE" in
            MIXIN_FATAL)
                log "TRIGGER | Mixin FATAL при загрузке — нужен фикс кода: $PATTERN_CTX"
                launch_claude "MIXIN_FATAL" "$PATTERN_CTX"
                ;;
            OOM)
                log "TRIGGER | OutOfMemoryError в логе"
                launch_claude "CRASH" "$PATTERN_CTX"
                ;;
            HUNG_TICK)
                log "TRIGGER | Minecraft Watchdog thread dump: $PATTERN_CTX"
                launch_claude "HUNG_TICK" "$PATTERN_CTX"
                ;;
            SPARK_STORM)
                log "TRIGGER | Spark timeout storm: $PATTERN_CTX"
                launch_claude "SPARK_TIMEOUT_STORM" "$PATTERN_CTX"
                ;;
        esac
    else
        # Нет новых строк — нет spark таймаутов
        echo 0 > "$SPARK_CONSEC_FILE"
    fi

    log "STATUS | OK — сервер работает (uptime ${UPTIME_SECS}s)"
    echo 0 > "$FAIL_COUNT_FILE"
    exit 0
fi

# Сервис остановлен вручную (inactive, not failed) — не трогаем
if ! systemctl is-failed youer --quiet 2>/dev/null; then
    log "STATUS | inactive (остановлен вручную) — пропускаю"
    exit 0
fi

# systemd исчерпал попытки автоперезапуска
log "STATUS | FAILED — сервер упал, systemd исчерпал попытки"
snapshot_new_log_lines || true

# ── Определяем: boot crash (упал при старте) или runtime crash ─────────────
# Смотрим на время активной фазы из журнала systemd
LAST_ACTIVE_TS=$(journalctl -u youer -n 200 --output=short-iso 2>/dev/null \
    | grep "Started\|start operation timed\|Main process exited" \
    | tail -1 | awk '{print $1}' || true)
BOOT_CRASH=0
if systemctl show youer --property=ActiveEnterTimestamp --value 2>/dev/null | grep -q "[0-9]"; then
    ENTER_TS=$(systemctl show youer --property=ActiveEnterTimestamp --value | head -1)
    DEACTIVATE_TS=$(systemctl show youer --property=InactiveEnterTimestamp --value | head -1)
    if [[ -n "$ENTER_TS" && -n "$DEACTIVATE_TS" && "$ENTER_TS" != "n/a" && "$DEACTIVATE_TS" != "n/a" ]]; then
        ENTER_EPOCH=$(date -d "$ENTER_TS" +%s 2>/dev/null || echo 0)
        DEACT_EPOCH=$(date -d "$DEACTIVATE_TS" +%s 2>/dev/null || echo 0)
        LIVED=$(( DEACT_EPOCH - ENTER_EPOCH ))
        if (( LIVED < BOOT_CRASH_MIN_UPTIME )); then
            BOOT_CRASH=1
            log "BOOT_CRASH | сервер прожил ${LIVED}s (< ${BOOT_CRASH_MIN_UPTIME}s) — boot crash"
        fi
    fi
fi

# ── Проверяем FATAL mixin в логе ───────────────────────────────────────────
MIXIN_FATAL_CTX=""
if [[ -s "$NEW_LINES_FILE" ]] || [[ -f "$SERVER_DIR/logs/latest.log" ]]; then
    CHECK_SRC="${NEW_LINES_FILE:-}"
    [[ ! -s "$CHECK_SRC" ]] && CHECK_SRC="$SERVER_DIR/logs/latest.log"
    MIXIN_FATAL_CTX=$(grep -E "\[main/FATAL\].*mixin|InvalidMixinException|Mixin prepare.*failed|target type mismatch" \
        "$CHECK_SRC" 2>/dev/null | head -8 | tr '\n' ' ' || true)
fi

if [[ -n "$MIXIN_FATAL_CTX" ]]; then
    log "BOOT_CRASH | обнаружен FATAL mixin: $MIXIN_FATAL_CTX"
    launch_claude "MIXIN_FATAL" "Mixin FATAL при загрузке: $MIXIN_FATAL_CTX"
    exit 0
fi

# ── Boot crash loop защита ─────────────────────────────────────────────────
if (( BOOT_CRASH == 1 )); then
    NOW_TS=$(date +%s)
    # Добавляем текущую метку, фильтруем старые
    {
        [[ -f "$BOOT_CRASH_LOOP_FILE" ]] && cat "$BOOT_CRASH_LOOP_FILE"
        echo "$NOW_TS"
    } | awk -v win="$((NOW_TS - BOOT_CRASH_LOOP_WINDOW))" '$1 > win' > "${BOOT_CRASH_LOOP_FILE}.tmp"
    mv "${BOOT_CRASH_LOOP_FILE}.tmp" "$BOOT_CRASH_LOOP_FILE"
    LOOP_COUNT=$(wc -l < "$BOOT_CRASH_LOOP_FILE" 2>/dev/null || echo 0)
    log "BOOT_CRASH | loop counter: ${LOOP_COUNT}/${BOOT_CRASH_LOOP_THRESHOLD} в окне ${BOOT_CRASH_LOOP_WINDOW}s"

    if (( LOOP_COUNT >= BOOT_CRASH_LOOP_THRESHOLD )); then
        log "BOOT_CRASH | LOOP DETECTED (${LOOP_COUNT} boot crashes в ${BOOT_CRASH_LOOP_WINDOW}s) — включаю maintenance mode"
        touch "$MAINTENANCE_FLAG"
        rm -f "$BOOT_CRASH_LOOP_FILE"
        # Запускаем Claude один раз с задачей разобраться в петле
        launch_claude "CRASH" "BOOT_CRASH_LOOP: сервер падает при старте ${LOOP_COUNT} раз подряд за ${BOOT_CRASH_LOOP_WINDOW}s. Сервер переведён в maintenance mode. Нужно найти причину, починить код, снять maintenance (rm $MAINTENANCE_FLAG) и запустить сервер."
        exit 0
    fi
fi

launch_claude "CRASH" ""
