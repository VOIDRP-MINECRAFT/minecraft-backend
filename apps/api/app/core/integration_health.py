"""One number for how well a server is connected: 0–100 and a grade (A+ … F).

Starts at 100 and loses points for what a player or its owner would feel: required modules
down, the server silent or unreachable from outside, unsupported or outdated plugins, clashing
plugins, a poor week of uptime, low TPS. Every deduction is listed, so the page can say why.
"""
from __future__ import annotations

from typing import Any


def grade(score: int) -> str:
    for limit, g in ((97, "A+"), (90, "A"), (80, "B"), (70, "C"), (55, "D")):
        if score >= limit:
            return g
    return "F"


def score(data: dict[str, Any]) -> dict[str, Any]:
    """From the «Интеграция» overview (``data``) — the same numbers the page shows."""
    factors: list[dict[str, Any]] = []

    def minus(points: float, why: str) -> None:
        if points > 0:
            factors.append({"points": -int(round(points)), "why": why})

    reports = data.get("reports") or []
    if not reports:
        return {"score": None, "grade": None, "factors": [{"points": 0, "why": "плагины VoidRP ещё не отчитывались"}]}
    if not any(r.get("fresh") for r in reports):
        minus(60, "сервер не отвечает")
    else:
        for r in data.get("required") or []:
            if not r.get("ok"):
                minus(35, f"не работает: {r.get('label')}")
    reach = data.get("reach") or {}
    if reach and reach.get("ok") is False and reach.get("address"):
        minus(25, f"снаружи сервер недоступен: {reach.get('error')}")
    for it in data.get("items") or []:
        if it.get("kind") != "ours":
            continue
        if it.get("unsupported"):
            minus(20, f"{it['name']} {it['installed']['version']} больше не поддерживается")
        elif it.get("outdated"):
            important = any(c.get("important") for c in it.get("changes_since_installed") or [])
            minus(10 if important else 4, f"{it['name']} устарел{' (важное обновление)' if important else ''}")
    for x in (data.get("inventory") or {}).get("issues") or []:
        minus({"err": 12, "warn": 4}.get(x.get("level"), 0), x.get("text", "")[:90])
    st = data.get("status") or {}
    up7 = st.get("uptime_7d")
    if up7 is not None and up7 < 99.5:
        minus(min(25, (99.5 - up7) * 2.5), f"аптайм за неделю {up7:.1f}%")
    tps = [p["tps"] for p in st.get("series_24h") or [] if p.get("tps") is not None]
    if tps:
        avg = sum(tps) / len(tps)
        if avg < 18.5:
            minus(min(20, (18.5 - avg) * 4), f"средний TPS за сутки {avg:.1f}")
    if (data.get("secret") or {}).get("old_secret_plugins"):
        minus(5, "часть плагинов ещё на старом секрете")
    total = max(0, min(100, 100 + sum(f["points"] for f in factors)))
    factors.sort(key=lambda f: f["points"])
    return {"score": total, "grade": grade(total), "factors": factors}
