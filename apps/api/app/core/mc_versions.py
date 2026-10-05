"""Which Minecraft versions a build is for, and whether a server's version is one of them.

A build lists entries (``plugin_releases.mc_versions``), each one of:

* ``26.2`` — exactly this version;
* ``1.21.x`` (or ``1.21.*``) — every 1.21 release;
* ``[1.21.4,1.21.11]`` — a range, ``[``/``]`` inclusive, ``(``/``)`` exclusive, either end may be
  empty (``[1.21.4,)`` — 1.21.4 and newer);
* ``>=1.21.4``, ``<1.22`` and the like.

A server matches a build when any entry takes its version; a build with no entries is for any.
"""
from __future__ import annotations

import re

_RANGE = re.compile(r"^([\[(])\s*([^,\s]*)\s*,\s*([^\])\s]*)\s*([\])])$")
_CMP = re.compile(r"^(>=|<=|>|<|=)\s*(\S+)$")


def key(v: str) -> tuple[int, ...]:
    """1.21.11 → (1, 21, 11); non-numeric parts end the version (26.2-rc1 → (26, 2))."""
    out = []
    for part in v.strip().split("."):
        digits = re.match(r"\d+", part)
        if not digits:
            break
        out.append(int(digits.group()))
        if digits.group() != part:
            break
    return tuple(out)


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def entry_matches(entry: str, mc: str) -> bool:
    entry = (entry or "").strip()
    if not entry:
        return False
    v = key(mc)
    if not v:
        return False
    if entry.endswith((".x", ".*")):
        prefix = key(entry[:-2])
        return bool(prefix) and v[:len(prefix)] == prefix
    m = _RANGE.match(entry)
    if m:
        lo_inc, lo, hi, hi_inc = m.group(1) == "[", m.group(2), m.group(3), m.group(4) == "]"
        if lo and (_cmp(v, key(lo)) < 0 or (not lo_inc and _cmp(v, key(lo)) == 0)):
            return False
        if hi and (_cmp(v, key(hi)) > 0 or (not hi_inc and _cmp(v, key(hi)) == 0)):
            return False
        return True
    m = _CMP.match(entry)
    if m:
        c = _cmp(v, key(m.group(2)))
        return {">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "=": c == 0}[m.group(1)]
    return _cmp(v, key(entry)) == 0 and bool(key(entry))


def matches(mc: str | None, entries: list[str] | None) -> bool:
    """Whether a server on ``mc`` may run a build listing ``entries`` (unknown mc: yes)."""
    if not entries or not (mc or "").strip():
        return True
    return any(entry_matches(e, mc) for e in entries)


def label(entries: list[str] | None) -> str:
    """For the page: «26.2», «1.21.4–1.21.11», «1.21.x»."""
    out = []
    for e in entries or []:
        m = _RANGE.match(e.strip())
        if m:
            lo, hi = m.group(2) or "…", m.group(3) or "…"
            out.append(f"{lo}–{hi}")
        else:
            out.append(e.strip())
    return ", ".join(out)
