"""Prometheus text-exposition exporter for the VoidRP game servers.

Turns the same per-server observations the admin monitoring panel shows
(host/JVM CPU & RAM, disk, online players, TPS/MSPT, unit & maintenance state)
into Prometheus gauges so the shared Grafana/Prometheus stack can graph them.

Design notes:
  • Collection is *pulled* on demand but served from a snapshot refreshed by a
    single daemon thread every ``ttl`` seconds. A scrape therefore always returns
    the last snapshot instantly and never blocks on RCON/mcstatus — a burst of
    scrapes (or a slow/dead RCON) can't stall Prometheus or pile up work.
  • Everything is best-effort and null-safe: a server missing its unit, RCON or
    ping simply omits those samples rather than failing the whole exposition.
  • Host metrics are emitted once (single box); node_exporter already covers the
    host in depth, these are just for convenience on the same dashboard.
"""
from __future__ import annotations

import threading
import time

from apps.api.app.core import server_ops
from apps.api.app.db import SessionLocal
from apps.api.app.repositories.game_server_repository import GameServerRepository

_NS = "voidrp"


# ── Exposition builder ───────────────────────────────────────────────────────
class _Exposition:
    """Accumulates gauge samples and renders valid Prometheus text format.

    One ``# HELP`` / ``# TYPE gauge`` header is emitted per metric name, before
    its samples, exactly as the format requires."""

    def __init__(self) -> None:
        self._families: dict[str, dict] = {}
        self._order: list[str] = []

    def gauge(self, name: str, value, help_text: str, labels: dict | None = None) -> None:
        if value is None:
            return
        full = f"{_NS}_{name}"
        fam = self._families.get(full)
        if fam is None:
            fam = {"help": help_text, "samples": []}
            self._families[full] = fam
            self._order.append(full)
        fam["samples"].append((labels or {}, value))

    def render(self) -> str:
        out: list[str] = []
        for name in self._order:
            fam = self._families[name]
            out.append(f"# HELP {name} {fam['help']}")
            out.append(f"# TYPE {name} gauge")
            for labels, value in fam["samples"]:
                out.append(f"{name}{_fmt_labels(labels)} {_fmt_value(value)}")
        return "\n".join(out) + "\n"


def _fmt_labels(labels: dict) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{_escape(str(v))}"' for k, v in labels.items()]
    return "{" + ",".join(parts) + "}"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_value(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return repr(float(value))


# ── Collection ───────────────────────────────────────────────────────────────
def _collect() -> str:
    """Build the full exposition from a fresh pass over every server. Runs in the
    refresher thread, so it may take a few seconds — that's fine, scrapes read the
    cached snapshot, not this."""
    started = time.monotonic()
    exp = _Exposition()
    host_emitted = False

    session = SessionLocal()
    try:
        servers = GameServerRepository(session).list_all()
    except Exception:
        servers = []
    finally:
        session.close()

    for srv in servers:
        slug = srv.slug
        lbl = {"server": slug}

        # Static/config state — always available from the DB row.
        exp.gauge("server_info", 1,
                  "Static server labels (value is always 1).",
                  {**lbl, "name": srv.name, "loader": srv.loader or "",
                   "mc_version": srv.mc_version or "", "default": "1" if srv.is_default else "0"})
        exp.gauge("server_maintenance", 1 if srv.maintenance else 0,
                  "1 if the server is flagged for maintenance.", lbl)

        # Host + JVM process + disk (best-effort; blocks ~0.35s for the CPU sample).
        try:
            m = server_ops.collect_metrics(srv)
        except Exception:
            m = None
        if m:
            state = (m.get("unit_state") or "").lower()
            exp.gauge("server_unit_active", 1 if state == "active" else 0,
                      "1 if the server's systemd unit is in the active state.", lbl)

            if not host_emitted and m.get("host"):
                h = m["host"]
                exp.gauge("host_cpu_percent", h.get("cpu_percent"), "Host CPU utilisation percent.")
                exp.gauge("host_mem_used_bytes", h.get("mem_used"), "Host memory used in bytes.")
                exp.gauge("host_mem_total_bytes", h.get("mem_total"), "Host memory total in bytes.")
                la = h.get("load_avg") or []
                if len(la) >= 1:
                    exp.gauge("host_load1", la[0], "Host 1-minute load average.")
                exp.gauge("host_uptime_seconds", h.get("uptime_seconds"), "Host uptime in seconds.")
                host_emitted = True

            p = m.get("process")
            if p:
                exp.gauge("server_process_cpu_percent", p.get("cpu_percent"),
                          "Server JVM process CPU percent.", lbl)
                exp.gauge("server_process_mem_bytes", p.get("mem_rss"),
                          "Server JVM process resident memory in bytes.", lbl)
                exp.gauge("server_process_threads", p.get("threads"),
                          "Server JVM process thread count.", lbl)
                exp.gauge("server_process_uptime_seconds", p.get("uptime_seconds"),
                          "Server JVM process uptime in seconds.", lbl)

            j = m.get("jvm")
            if j:
                exp.gauge("server_jvm_heap_used_bytes", j.get("heap_used"),
                          "Server JVM heap used in bytes.", lbl)
                exp.gauge("server_jvm_heap_committed_bytes", j.get("heap_committed"),
                          "Server JVM heap committed in bytes.", lbl)
                exp.gauge("server_jvm_heap_max_bytes", j.get("heap_max"),
                          "Server JVM heap max (-Xmx) in bytes.", lbl)

            d = m.get("disk")
            if d:
                exp.gauge("server_disk_used_bytes", d.get("used"),
                          "Server data-dir disk used in bytes.", lbl)
                exp.gauge("server_disk_total_bytes", d.get("total"),
                          "Server data-dir disk total in bytes.", lbl)

        # Live players (ping) — also our reachability signal.
        try:
            players = server_ops.collect_players(srv)
        except Exception:
            players = None
        exp.gauge("server_up", 1 if players is not None else 0,
                  "1 if the server answered a status/query ping.", lbl)
        if players is not None:
            exp.gauge("server_players_online", players.get("online"),
                      "Online player count.", lbl)
            if players.get("max") is not None:
                exp.gauge("server_players_max", players.get("max"),
                          "Max player slots.", lbl)

        # TPS / MSPT (RCON) — only if configured; short timeout inside.
        try:
            tps = server_ops.query_tps(srv)
        except Exception:
            tps = None
        if tps:
            exp.gauge("server_tps", tps.get("tps"), "Server ticks per second (overall).", lbl)
            if tps.get("mspt") is not None:
                exp.gauge("server_mspt", tps.get("mspt"),
                          "Server milliseconds per tick (overall).", lbl)
            for dim in (tps.get("dimensions") or []):
                dlbl = {**lbl, "dimension": dim.get("dim", "")}
                exp.gauge("server_dimension_tps", dim.get("tps"),
                          "Per-dimension ticks per second.", dlbl)
                if dim.get("mspt") is not None:
                    exp.gauge("server_dimension_mspt", dim.get("mspt"),
                              "Per-dimension milliseconds per tick.", dlbl)

    exp.gauge("exporter_scrape_duration_seconds", round(time.monotonic() - started, 3),
              "Time the last collection pass took.")
    exp.gauge("exporter_servers_total", len(servers),
              "Number of game servers considered.")
    return exp.render()


# ── Snapshot cache + refresher thread ────────────────────────────────────────
_lock = threading.Lock()
_snapshot: str | None = None
_snapshot_ts: float = 0.0
_thread: threading.Thread | None = None
_ttl: float = 15.0


def _refresher() -> None:
    global _snapshot, _snapshot_ts
    while True:
        try:
            text = _collect()
            with _lock:
                _snapshot = text
                _snapshot_ts = time.time()
        except Exception:
            # Never let the refresher die — a bad pass just leaves the old snapshot.
            pass
        time.sleep(_ttl)


def _ensure_thread() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_refresher, name="prometheus-exporter",
                                   daemon=True)
        _thread.start()


def render_metrics(ttl: float = 15.0) -> str:
    """Return the current exposition snapshot, starting the refresher on first
    call and doing one synchronous collection if no snapshot exists yet."""
    global _ttl
    _ttl = max(5.0, float(ttl))
    _ensure_thread()
    with _lock:
        snap = _snapshot
    if snap is None:
        # Cold start: build once inline so the very first scrape isn't empty.
        snap = _collect()
        with _lock:
            snap2 = _snapshot
        if snap2 is not None:
            return snap2
    return snap or ""
