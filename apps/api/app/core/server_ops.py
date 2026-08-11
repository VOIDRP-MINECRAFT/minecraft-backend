"""Host/process observation & RCON control for the admin monitoring panel.

The backend and every game server run under the same OS user on the same host,
so given only a systemd unit name we can read the running JVM's PID and working
directory and derive CPU / RAM / disk without any elevated privileges. RCON
drives the live console, TPS, player list and moderation.

Everything here is best-effort and null-safe: a server missing its unit or RCON
config yields ``None`` fields rather than raising, so the panel degrades to
"not configured" instead of erroring.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    from apps.api.app.models.game_server import GameServer

# Reuse one psutil.Process per PID so cpu_percent() measures the delta between
# polls (the panel polls every few seconds → accurate load without a big sleep).
_proc_cache: dict[int, psutil.Process] = {}


# ── systemd introspection ──────────────────────────────────────────────────
def _systemctl_bin() -> str:
    """Absolute path to systemctl. The backend runs as a systemd service whose
    PATH is narrowed to the venv bin, so a bare ``systemctl`` isn't found — we
    must call it by absolute path."""
    for candidate in ("/usr/bin/systemctl", "/bin/systemctl", "/usr/sbin/systemctl"):
        if os.path.exists(candidate):
            return candidate
    return shutil.which("systemctl") or "systemctl"


_SYSTEMCTL = _systemctl_bin()


def _systemctl_props(unit: str, props: tuple[str, ...]) -> dict[str, str]:
    """Fetch several unit properties in a single systemctl call → {prop: value}.
    Batching avoids spawning one subprocess per property on every metrics poll."""
    args = [_SYSTEMCTL, "show", unit]
    for p in props:
        args += ["-p", p]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return {}
    out: dict[str, str] = {}
    for line in (res.stdout or "").splitlines():
        key, sep, val = line.partition("=")
        if sep:
            out[key.strip()] = val.strip()
    return out


def _systemctl_show(unit: str, prop: str) -> str | None:
    return _systemctl_props(unit, (prop,)).get(prop) or None


def resolve_data_dir(server: "GameServer") -> str | None:
    if server.data_dir:
        return server.data_dir
    if server.systemd_unit:
        return _systemctl_show(server.systemd_unit, "WorkingDirectory")
    return None


def resolve_log_path(server: "GameServer") -> str | None:
    if server.log_path:
        return server.log_path
    data_dir = resolve_data_dir(server)
    if data_dir:
        return os.path.join(data_dir, "logs", "latest.log")
    return None


# ── Metrics ─────────────────────────────────────────────────────────────────
@dataclass
class HostMetrics:
    cpu_percent: float
    cpu_count: int
    load_avg: list[float]
    mem_total: int
    mem_used: int
    mem_percent: float
    uptime_seconds: int


@dataclass
class ProcessMetrics:
    pid: int
    cpu_percent: float
    mem_rss: int
    mem_percent: float
    threads: int
    uptime_seconds: int


@dataclass
class DiskMetrics:
    path: str
    mountpoint: str
    device: str
    fstype: str
    total: int
    used: int
    free: int
    percent: float


def _disk_for(path: str) -> DiskMetrics | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    mountpoint, device, fstype = path, "", ""
    try:
        best = ""
        for part in psutil.disk_partitions(all=False):
            if path.startswith(part.mountpoint) and len(part.mountpoint) >= len(best):
                best = part.mountpoint
                mountpoint, device, fstype = part.mountpoint, part.device, part.fstype
    except Exception:
        pass
    return DiskMetrics(
        path=path,
        mountpoint=mountpoint,
        device=device,
        fstype=fstype,
        total=usage.total,
        used=usage.used,
        free=usage.free,
        percent=round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
    )


def _prune_proc_cache() -> None:
    for pid in [p for p, proc in _proc_cache.items() if not proc.is_running()]:
        _proc_cache.pop(pid, None)
        _jcmd_maxheap_cache.pop(pid, None)


def collect_metrics(server: "GameServer") -> dict:
    """Host + per-server-process + disk snapshot. Blocks ~0.35s for a CPU sample
    (runs in FastAPI's threadpool, so it doesn't stall the event loop)."""
    # One systemctl call for MainPID + WorkingDirectory + ActiveState.
    unit = server.systemd_unit
    props = _systemctl_props(unit, ("MainPID", "WorkingDirectory", "ActiveState")) if unit else {}
    pid_raw = props.get("MainPID", "")
    pid = int(pid_raw) if pid_raw.isdigit() and int(pid_raw) > 0 else None
    state = props.get("ActiveState") or None
    data_dir = server.data_dir or props.get("WorkingDirectory") or None

    _prune_proc_cache()
    proc: psutil.Process | None = None
    if pid is not None:
        proc = _proc_cache.get(pid)
        if proc is None or not proc.is_running():
            try:
                proc = psutil.Process(pid)
                _proc_cache[pid] = proc
            except psutil.Error:
                proc = None

    # Prime CPU counters, sleep briefly, then read the delta.
    psutil.cpu_percent(interval=None)
    if proc is not None:
        try:
            proc.cpu_percent(None)
        except psutil.Error:
            proc = None
    time.sleep(0.35)

    vm = psutil.virtual_memory()
    try:
        load_avg = list(os.getloadavg())
    except OSError:
        load_avg = [0.0, 0.0, 0.0]
    host = HostMetrics(
        cpu_percent=round(psutil.cpu_percent(interval=None), 1),
        cpu_count=psutil.cpu_count() or 1,
        load_avg=[round(x, 2) for x in load_avg],
        mem_total=vm.total,
        mem_used=vm.total - vm.available,
        mem_percent=vm.percent,
        uptime_seconds=int(time.time() - psutil.boot_time()),
    )

    process: ProcessMetrics | None = None
    if proc is not None:
        try:
            with proc.oneshot():
                process = ProcessMetrics(
                    pid=proc.pid,
                    cpu_percent=round(proc.cpu_percent(None), 1),
                    mem_rss=proc.memory_info().rss,
                    mem_percent=round(proc.memory_percent(), 1),
                    threads=proc.num_threads(),
                    uptime_seconds=int(time.time() - proc.create_time()),
                )
        except psutil.Error:
            process = None

    disk = _disk_for(data_dir) if data_dir else None
    jvm = collect_jvm(proc) if proc is not None else None

    return {
        "unit": unit,
        "unit_state": state,
        "data_dir": data_dir,
        "host": host.__dict__ if host else None,
        "process": process.__dict__ if process else None,
        "disk": disk.__dict__ if disk else None,
        "jvm": jvm,
    }


# ── JVM heap (via jcmd — same OS user, no elevated privileges) ───────────────
# jcmd ships in the JDK next to the ``java`` binary and talks to the target VM
# over its attach socket, so it works even when the server is launched with
# ``-XX:+PerfDisableSharedMem`` (which our servers are — that flag kills the
# hsperfdata file jstat/jstat-style tools rely on, but not the attach channel).
# GC.heap_info gives live heap used + committed; VM.flags gives MaxHeapSize (the
# effective -Xmx), cached since it never changes for a running VM. GC pause
# counters aren't reachable without perfdata, so we omit them rather than lie.
# Everything is best-effort: no jcmd, a failed attach, or a parse miss → ``None``.
_jcmd_maxheap_cache: dict[int, int] = {}
_HEAP_INFO_RE = re.compile(r"total\s+(\d+)K,\s*used\s+(\d+)K")
_META_INFO_RE = re.compile(r"Metaspace\s+used\s+(\d+)K,\s*committed\s+(\d+)K")
_MAXHEAP_RE = re.compile(r"MaxHeapSize=(\d+)")


def _jcmd_bin(proc: psutil.Process) -> str | None:
    try:
        exe = proc.exe()  # …/jdk/bin/java  → jcmd sits alongside it
        cand = os.path.join(os.path.dirname(exe), "jcmd")
        if os.path.exists(cand):
            return cand
    except (psutil.Error, OSError):
        pass
    if os.path.exists("/usr/bin/jcmd"):
        return "/usr/bin/jcmd"
    return shutil.which("jcmd")


def _run_jcmd(jcmd: str, pid: int, cmd: str) -> str | None:
    try:
        res = subprocess.run([jcmd, str(pid), cmd], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    out = res.stdout or ""
    if not out or "Could not attach" in out or "Exception" in out:
        return None
    return out


def _jvm_max_heap(jcmd: str, pid: int) -> int | None:
    cached = _jcmd_maxheap_cache.get(pid)
    if cached is not None:
        return cached
    flags = _run_jcmd(jcmd, pid, "VM.flags")
    m = _MAXHEAP_RE.search(flags or "")
    if m:
        val = int(m.group(1))
        _jcmd_maxheap_cache[pid] = val
        return val
    return None


def collect_jvm(proc: psutil.Process) -> dict | None:
    jcmd = _jcmd_bin(proc)
    if not jcmd:
        return None
    pid = proc.pid
    info = _run_jcmd(jcmd, pid, "GC.heap_info")
    if not info:
        return None
    heap = _HEAP_INFO_RE.search(info)
    if not heap:
        return None
    committed = int(heap.group(1)) * 1024  # "total" for G1 = current committed heap
    heap_used = int(heap.group(2)) * 1024
    heap_max = _jvm_max_heap(jcmd, pid) or committed
    meta = _META_INFO_RE.search(info)
    return {
        "heap_used": heap_used,
        "heap_committed": committed,
        "heap_max": heap_max,
        "heap_percent": round(heap_used / heap_max * 100, 1) if heap_max else None,
        "meta_used": int(meta.group(1)) * 1024 if meta else None,
    }


# ── Power control (systemctl start / restart / stop) ────────────────────────
# The backend and the game servers run as the same OS user, but the units are
# *system* services, so managing them still requires a polkit/sudoers grant for
# that user (see scripts/polkit/49-voidrp-server-power.rules). We enqueue the job
# with --no-block so the HTTP call returns immediately and the panel watches the
# unit state flip via the metrics poll; a missing grant surfaces as PowerError.
_POWER_ACTIONS = frozenset({"start", "restart", "stop"})


class PowerError(RuntimeError):
    pass


class PowerNotConfigured(PowerError):
    pass


def power_action(server: "GameServer", action: str, timeout: float = 15.0) -> str:
    """Run ``systemctl <action> <unit>`` for the server's unit. Returns any
    stdout on success; raises ``PowerNotConfigured`` if the server has no unit
    and ``PowerError`` on any systemctl failure (incl. "authentication required"
    when the polkit/sudoers grant is missing)."""
    if action not in _POWER_ACTIONS:
        raise PowerError(f"Неизвестное действие: {action}")
    unit = server.systemd_unit
    if not unit:
        raise PowerNotConfigured("systemd-юнит не настроен для этого сервера")
    args = [_SYSTEMCTL, action, "--no-block", unit]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PowerError(f"systemctl {action} превысил таймаут")
    except (OSError, subprocess.SubprocessError) as exc:
        raise PowerError(str(exc))
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "").strip() or f"код выхода {res.returncode}"
        raise PowerError(msg)
    return (res.stdout or "").strip()


# ── RCON ────────────────────────────────────────────────────────────────────
# Self-contained Source RCON client. We avoid the `mcrcon` package because it
# implements its read timeout with signal.alarm(), which only works in the main
# thread — and FastAPI runs sync endpoints in a threadpool, so it would crash
# with "signal only works in main thread". A plain socket + settimeout works in
# any thread and lets us assemble multi-packet responses (long TPS/help output).
_RCON_AUTH = 3
_RCON_EXEC = 2


class RconNotConfigured(RuntimeError):
    pass


class RconAuthError(RuntimeError):
    pass


def _rcon_pack(req_id: int, ptype: int, body: str) -> bytes:
    payload = struct.pack("<ii", req_id, ptype) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def _rcon_recv_exact(sock: socket.socket, n: int, deadline: float) -> bytes:
    buf = b""
    while len(buf) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("RCON overall timeout")
        sock.settimeout(remaining)
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("RCON socket closed")
        buf += chunk
    return buf


def _rcon_read_packet(sock: socket.socket, deadline: float) -> tuple[int, int, str]:
    (length,) = struct.unpack("<i", _rcon_recv_exact(sock, 4, deadline))
    payload = _rcon_recv_exact(sock, length, deadline)
    req_id, ptype = struct.unpack("<ii", payload[:8])
    body = payload[8:-2].decode("utf-8", errors="replace")
    return req_id, ptype, body


def rcon_command(server: "GameServer", command: str, timeout: float = 6.0) -> str:
    """Run a single RCON command and return the concatenated server response.

    ``timeout`` is an overall wall-clock budget for the whole exchange (connect
    + auth + all response packets), so a server that dribbles output slowly
    can't stall the caller past it."""
    host = server.rcon_host or "127.0.0.1"
    port = server.rcon_port
    password = server.rcon_password
    if not port or password is None:
        raise RconNotConfigured("RCON is not configured for this server")

    deadline = time.monotonic() + timeout
    with socket.create_connection((host, port), timeout=timeout) as sock:
        # Authenticate: the auth reply echoes our id, or -1 on failure. Some
        # servers emit a spurious empty packet first, so skip until we get one
        # that isn't the empty pre-auth frame.
        sock.sendall(_rcon_pack(_RCON_EXEC, _RCON_AUTH, password))
        authed = False
        for _ in range(3):
            req_id, _ptype, _body = _rcon_read_packet(sock, deadline)
            if req_id == -1:
                raise RconAuthError("RCON authentication failed (wrong password)")
            if req_id == _RCON_EXEC:
                authed = True
                break
        if not authed:
            raise RconAuthError("RCON authentication not confirmed by server")

        # Minecraft's RCON returns the whole result in a single response packet
        # (unlike Source, it doesn't split at 4096 bytes), so we read exactly one
        # reply. We deliberately do NOT use the "empty exec" multi-packet sentinel
        # trick: on Mohist/CraftBukkit an empty command hits CraftServer.dispatch
        # → args[0] on a 0-length array → ArrayIndexOutOfBoundsException spam.
        sock.sendall(_rcon_pack(_RCON_EXEC, _RCON_EXEC, command))
        _req_id, _ptype, body = _rcon_read_packet(sock, deadline)
        return body


# ── Player list (via mcstatus query/ping — locale-proof, gives real names) ──
def _player_endpoints(server: "GameServer") -> list[tuple[str, int]]:
    """Ordered (host, port) candidates to ping for player info. Local servers
    (those with a systemd unit) are pinged on 127.0.0.1 first — the host often
    can't reach its own public hostname (NAT hairpin), which is why the public
    ``host`` value alone times out from the backend box."""
    port = server.status_port or server.port or 25565
    cands: list[tuple[str, int]] = []
    if server.status_host:
        cands.append((server.status_host, port))
    # Loopback is only valid for a server that runs on THIS host (has a unit) —
    # for a remote server 127.0.0.1 would ping whatever local server sits on that
    # port and report the wrong data.
    if server.systemd_unit:
        cands.append(("127.0.0.1", server.port or port))
        cands.append(("127.0.0.1", port))
    cands.append((server.host or "127.0.0.1", server.port or port))
    seen: set[tuple[str, int]] = set()
    return [c for c in cands if not (c in seen or seen.add(c))]


def collect_players(server: "GameServer") -> dict | None:
    """Online count / max / names for the server. Tries the GameSpy query
    protocol (full name list) then the SLP ping sample across candidate
    endpoints. Returns ``None`` only if the server can't be reached at all."""
    from mcstatus import JavaServer

    for host, port in _player_endpoints(server):
        online: int | None = None
        mx: int | None = None
        names: list[str] = []
        try:
            q = JavaServer(host, port, timeout=3).query()
            online, mx = q.players.online, q.players.max
            names = list(getattr(q.players, "list", None) or getattr(q.players, "names", []) or [])
        except Exception:
            pass
        if online is None or not names:
            try:
                st = JavaServer(host, port, timeout=3).status()
                if online is None:
                    online, mx = st.players.online, st.players.max
                if not names:
                    names = [p.name for p in (st.players.sample or [])]
            except Exception:
                pass
        if online is not None:
            return {"online": online or 0, "max": mx, "players": sorted(names, key=str.lower)}
    return None


# ── TPS / MSPT (via RCON; handles Paper `tps` and localized NeoForge) ───────
def query_tps(server: "GameServer", timeout: float = 3.0) -> dict | None:
    """Best-effort TPS/MSPT via RCON. Paper/Purpur `tps` gives 5s/1m/5m/15m
    windows; NeoForge `neoforge tps` gives per-dimension + an overall line.
    Short timeout + bail-out on connection errors so a dead RCON doesn't stall
    the /live poll."""
    if not (server.rcon_port and server.rcon_password is not None):
        return None

    # Query the loader's own command first so the common case is one RCON
    # round-trip (matters for slow/laggy servers): Paper-family → `tps`,
    # everything else → `neoforge tps`. Fall back to the other on a miss.
    loader = (server.loader or "").lower()
    paper_like = any(k in loader for k in ("paper", "purpur", "spigot", "bukkit", "mohist", "folia"))
    cmds = ["tps", "neoforge tps"] if paper_like else ["neoforge tps", "tps"]

    for cmd in cmds:
        try:
            raw = strip_color_codes(rcon_command(server, cmd, timeout=timeout) or "")
        except (RconNotConfigured, OSError):
            return None  # RCON unreachable — don't keep trying
        except Exception:
            continue
        parsed = _parse_tps(raw)
        if parsed:
            return parsed
    return None


def _tps_pair(line: str) -> dict | None:
    """Pull (tps, mspt) from one NeoForge tps line. The localized/overall form
    is ``… 20.0 тактов/сек (25.4 мс/такт)`` → first number is TPS, second MSPT.
    Anything before the first ':' is a label and is dropped so a ``minecraft:``
    dimension token in the name never leaks into the numbers."""
    nums = _floats(line.split(":", 1)[-1] if ":" in line else line)
    if not nums:
        return None
    return {"tps": round(min(nums[0], 20.0), 1),
            "mspt": round(nums[1], 2) if len(nums) > 1 else None}


_DIM_RE = re.compile(r"([a-z0-9_.-]+:[a-z0-9_./-]+)")
# Overall/summary line keyword (EN + RU) — distinguishes it from per-dim lines.
_OVERALL_RE = re.compile(r"overall|в целом|итог", re.IGNORECASE)


def _parse_tps(raw: str) -> dict | None:
    # Paper/Purpur: "TPS from last 5s, 1m, 5m, 15m: 20.0, 19.2, ..."
    if "TPS from last" in raw:
        nums = _floats(raw.split(":", 1)[-1])
        if nums:
            labels = ["5s", "1m", "5m", "15m"]
            windows = {labels[i]: round(nums[i], 1) for i in range(min(len(nums), 4))}
            return {"tps": round(nums[0], 1), "mspt": None, "windows": windows,
                    "dimensions": None, "source": "paper"}
    # NeoForge: one line per loaded dimension + an overall line. The overall line
    # carries no ``namespace:path`` token; each dimension line does. We keep the
    # full per-dimension breakdown so the panel can point at *which* dimension lags.
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if lines and ("тактов" in raw or "TPS" in raw or "tick" in raw.lower()):
        dims: list[dict] = []
        overall: dict | None = None
        last_total: dict | None = None  # last numeric line that was NOT a dimension
        for ln in lines:
            pair = _tps_pair(ln)
            if not pair:
                continue
            dim = _DIM_RE.search(ln)
            if dim and not _OVERALL_RE.search(ln):
                dims.append({"dim": dim.group(1), **pair})
                continue
            last_total = pair
            if _OVERALL_RE.search(ln):
                overall = pair  # explicit "Overall"/"В целом" line wins
        # No explicit overall keyword → last non-dimension line (original
        # behaviour), else the worst dimension so the headline still shows lag.
        if overall is None:
            if last_total is not None:
                overall = last_total
            elif dims:
                worst = min(dims, key=lambda d: d["tps"])
                overall = {"tps": worst["tps"], "mspt": worst["mspt"]}
        if overall:
            return {"tps": overall["tps"], "mspt": overall["mspt"],
                    "windows": None, "dimensions": dims or None, "source": "neoforge"}
    return None


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _floats(text: str) -> list[float]:
    """Extract well-formed numbers (ints/decimals), skipping version tokens and
    stray dots that would break a naive float() call."""
    out: list[float] = []
    for tok in _NUM_RE.findall(text):
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


_CODE_RE = re.compile(r"§.")


def strip_color_codes(text: str) -> str:
    return _CODE_RE.sub("", text or "")


# ── Log tail ────────────────────────────────────────────────────────────────
def tail_log(path: str, lines: int = 200, max_bytes: int = 512 * 1024) -> list[str]:
    """Return the last ``lines`` lines of a log file, reading only the tail."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # drop partial first line
            data = fh.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    out = text.splitlines()
    return out[-lines:]


# ── Hang / Watchdog scanner ─────────────────────────────────────────────────
# Surfaces the headline lines of watchdog stalls (HUNG_TICK) so they don't have
# to be hunted for by scrolling the log. We match only the *summary* lines a
# stall emits — not the hundreds of stack frames that follow — and pull out the
# timestamp and, where present, the tick duration in seconds.
_HANG_LINE_RE = re.compile(
    r"single server tick took|appears to be hung|Considering it to be crashed"
    r"|HUNG_TICK|HUNG TICK|Watchdog",
    re.IGNORECASE,
)
# A stack dump has thousands of these; keep them out of the summary list.
_HANG_NOISE_RE = re.compile(r"\bat [\w.$]+\(|java\.|\tat |Thread\.State|Daemon Thread")
_TS_RE = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")
_HANG_SECS_RE = re.compile(r"took ([\d.]+)\s*sec", re.IGNORECASE)


def scan_hangs(path: str, scan_lines: int = 6000, limit: int = 50) -> list[dict]:
    """Scan the tail of a log for watchdog/hang summary lines, newest last.
    Returns ``[{time, seconds, text}]``. Empty list if the file is unreadable."""
    hits: list[dict] = []
    for ln in tail_log(path, lines=scan_lines, max_bytes=3 * 1024 * 1024):
        if not _HANG_LINE_RE.search(ln) or _HANG_NOISE_RE.search(ln):
            continue
        ts = _TS_RE.search(ln)
        secs = _HANG_SECS_RE.search(ln)
        hits.append({
            "time": ts.group(1) if ts else None,
            "seconds": float(secs.group(1)) if secs else None,
            "text": strip_color_codes(ln).strip(),
        })
    return hits[-limit:]
