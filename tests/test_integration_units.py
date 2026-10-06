"""Pure pieces of «Интеграция»: Minecraft version ranges, plugin version order, reading a GitHub
release, the health grade, the Telegram card and the digest wording, the status badge."""
from __future__ import annotations

import pytest

from apps.api.app.core import integration_brief as brief
from apps.api.app.core import integration_health as health
from apps.api.app.core import mc_versions
from apps.api.app.core.releases import version_key


# ── Minecraft versions ────────────────────────────────────────────────────────
@pytest.mark.parametrize("entry,mc,ok", [
    ("26.2", "26.2", True),
    ("26.2", "26.2.1", False),
    ("1.21.x", "1.21.11", True),
    ("1.21.*", "1.22", False),
    ("[1.21.4,1.21.11]", "1.21.4", True),
    ("[1.21.4,1.21.11]", "1.21.11", True),
    ("[1.21.4,1.21.11)", "1.21.11", False),
    ("(1.21.4,1.21.11]", "1.21.4", False),
    ("[1.21.4,)", "26.2", True),
    ("[,1.21)", "1.20.6", True),
    (">=1.21.4", "1.21.3", False),
    ("<1.22", "1.21.11", True),
    ("26.2", "26.2-rc1", True),
    ("", "26.2", False),
])
def test_mc_entry(entry: str, mc: str, ok: bool) -> None:
    assert mc_versions.entry_matches(entry, mc) is ok


def test_mc_matches_any_and_unknown() -> None:
    assert mc_versions.matches("26.2", ["1.21.x", "26.2"])
    assert not mc_versions.matches("1.20.1", ["1.21.x", "26.2"])
    assert mc_versions.matches(None, ["26.2"])  # unknown server version: allowed
    assert mc_versions.matches("1.20.1", [])  # build for any version


def test_mc_key_numeric() -> None:
    assert mc_versions.key("1.21.11") > mc_versions.key("1.21.9")
    assert mc_versions.key("26.2-rc1") == (26, 2)


# ── Plugin versions ───────────────────────────────────────────────────────────
def test_version_order() -> None:
    ordered = ["0.5.0", "0.6.0-beta.1", "0.6.0", "0.6.1", "0.10.0", "1.0.0"]
    assert sorted(reversed(ordered), key=version_key) == ordered


def test_version_none_and_equal() -> None:
    assert version_key("1.4.0") == version_key("1.4.0")
    assert version_key(None) < version_key("0.0.1")


# ── Reading a GitHub release ──────────────────────────────────────────────────
def test_release_targets_from_jar_name() -> None:
    from apps.worker.release_sync import _jars, _targets

    entry = {"cores": ["paper", "folia"], "release": {"by_mc": {"1.21.4": ["paper"]}}}
    assert _targets(entry, "VoidRpPerms-0.7.0+mc26.2.jar", {}) == (["paper", "folia"], ["26.2"])
    plat, mc = _targets(entry, "VoidRpPerms-0.7.0+mc1.21.4-1.21.11.jar", {})
    assert plat == ["paper"] and mc == ["[1.21.4,1.21.11]"]
    # release.json wins over the name
    manifest = {"jars": {"x.jar": {"platforms": ["neoforge"], "mc": ["26.2"]}}}
    assert _targets(entry, "x.jar", manifest) == (["neoforge"], ["26.2"])
    # shadow jar preferred, sources skipped
    rel = {"assets": [{"name": "a-1.0.jar"}, {"name": "a-1.0-all.jar"}, {"name": "a-1.0-sources.jar"}]}
    assert [a["name"] for a in _jars(rel)] == ["a-1.0-all.jar"]


# ── Health grade ──────────────────────────────────────────────────────────────
def _data(**over):
    base = {
        "reports": [{"fresh": True}],
        "required": [{"label": "Вход", "ok": True}, {"label": "Мониторинг", "ok": True}],
        "items": [], "inventory": {"issues": []},
        "status": {"uptime_7d": 100.0, "series_24h": [{"tps": 20.0}]},
        "reach": None, "secret": {},
    }
    base.update(over)
    return base


def test_health_perfect() -> None:
    h = health.score(_data())
    assert h["score"] == 100 and h["grade"] == "A+" and h["factors"] == []


def test_health_silent_server_is_bad() -> None:
    h = health.score(_data(reports=[{"fresh": False}]))
    assert h["score"] <= 40 and h["grade"] == "F"


def test_health_outdated_and_module_down() -> None:
    items = [{"kind": "ours", "name": "VoidRpPerms", "installed": {"version": "0.5.0"}, "outdated": True,
              "changes_since_installed": [{"important": True}]}]
    h = health.score(_data(items=items, required=[{"label": "Вход", "ok": False}]))
    assert h["score"] == 100 - 35 - 10
    assert any("Вход" in f["why"] for f in h["factors"])


def test_health_no_reports() -> None:
    assert health.score(_data(reports=[]))["grade"] is None


@pytest.mark.parametrize("score,g", [(100, "A+"), (97, "A+"), (96, "A"), (85, "B"), (72, "C"), (60, "D"), (10, "F")])
def test_grade_bounds(score: int, g: str) -> None:
    assert health.grade(score) == g


# ── Telegram card and digest wording ──────────────────────────────────────────
class _Srv:
    name = "Test <b>"
    slug = "test"
    maintenance = False


def test_state_of() -> None:
    assert brief.state_of({"reports": []})[0] == "⚪"
    assert brief.state_of({"reports": [{"fresh": False}]})[0] == "🔴"
    assert brief.state_of({"reports": [{"fresh": True}], "missing_required": ["Вход"]})[0] == "🟠"
    assert brief.state_of({"reports": [{"fresh": True}], "missing_required": []})[0] == "🟢"


def test_card_escapes_and_lists_updates() -> None:
    data = _data(
        missing_required=[],
        items=[{"kind": "ours", "name": "VoidRpAuth", "outdated": True, "installed": {"version": "1.3.0"},
                "latest": {"version": "1.4.0"}}],
        health={"grade": "B", "score": 88},
        settings={"auto_update": True},
        status={"uptime_24h": 100.0, "uptime_7d": 99.5, "series_24h": [{"online": 3, "tps": 19.8}]},
    )
    text = brief.card(_Srv(), data)
    assert "Test &lt;b&gt;" in text  # the server name is escaped for HTML mode
    assert "VoidRpAuth 1.3.0 → 1.4.0" in text
    assert "игроков 3" in text and "TPS 19.8" in text
    assert "автообновление: включено" in text


def test_pct_format() -> None:
    assert brief._pct(None) == "нет данных"
    assert brief._pct(100.0) == "100%"
    assert brief._pct(99.5) == "99.5%"


# ── Status badge ──────────────────────────────────────────────────────────────
def test_badge_width_grows_with_text() -> None:
    from apps.api.app.api.routes.status_public import _text_width

    assert _text_width("● 10/100 онлайн") > _text_width("● 1/10 онлайн")
    assert _text_width("abc", bold=True) > _text_width("abc")
