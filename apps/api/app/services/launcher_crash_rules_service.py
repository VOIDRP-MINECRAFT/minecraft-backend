"""Launcher crash rules: validation, merging over the launcher's built-ins, and matching.

The launcher (CoreHost ``CrashAdvisor``) evaluates the rules with .NET regexes; this module
re-implements the same matching with Python ``re`` so admins can test a rule against real
crash reports before shipping it. Keep the semantics in sync with ``CrashAdvisor.TryMatch``:
every ``patterns_all`` must match, at least one ``patterns_any`` if the list is non-empty,
and the exit code must be listed when ``exit_codes`` is non-empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.app.models.game_server import GameServer
from apps.api.app.models.launcher_crash_report import LauncherCrashReport
from apps.api.app.models.launcher_crash_rule import LauncherCrashRule

BUILTIN_RULES_PATH = Path(__file__).resolve().parent.parent / "core" / "launcher_crash_rules_builtin.json"

# Executed by the launcher core / handled by the launcher UI (see CrashActionTypes in CoreHost).
ACTION_TYPES = {
    "fix_files": "Убрать файлы",
    "reset_config": "Сбросить конфиг из лога ({file})",
    "reset_all_configs": "Сбросить все настройки модов",
    "repair": "Починить клиент",
    "open_settings": "Открыть настройки памяти",
    "relaunch": "Запустить снова",
    "copy_report": "Скопировать отчёт",
}

KEY_RE = re.compile(r"^[a-z0-9_]{3,64}$")
MAX_PATTERNS = 10
MAX_PATTERN_LEN = 500
MAX_ACTIONS = 4
MAX_PATHS = 5
DEFAULT_RECOMMENDED_RAM_MB = 6144


@lru_cache(maxsize=1)
def load_builtin_rules() -> list[dict[str, Any]]:
    """Exported from the launcher's CrashAdvisor.BuiltInRules — re-export when those change."""
    return json.loads(BUILTIN_RULES_PATH.read_text(encoding="utf-8"))


def to_python_pattern(pattern: str) -> str:
    """.NET named groups ``(?<name>...)`` → Python ``(?P<name>...)`` (lookbehinds untouched)."""
    return re.sub(r"\(\?<(?![=!])", "(?P<", pattern)


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(to_python_pattern(pattern), re.IGNORECASE)
    except re.error:
        return None


def rule_to_dict(rule: LauncherCrashRule) -> dict[str, Any]:
    return {
        "key": rule.key,
        "priority": rule.priority,
        "enabled": rule.enabled,
        "patterns_all": list(rule.patterns_all or []),
        "patterns_any": list(rule.patterns_any or []),
        "exit_codes": list(rule.exit_codes or []),
        "title": rule.title,
        "cause": rule.cause or "",
        "solution": rule.solution or "",
        "actions": list(rule.actions or []),
    }


def validate_rule(data: dict[str, Any]) -> list[str]:
    """Human-readable (RU, admin UI) problems with a rule payload; empty list = valid."""
    errors: list[str] = []
    if not KEY_RE.match(str(data.get("key") or "")):
        errors.append("Ключ: 3–64 символа, только латиница в нижнем регистре, цифры и _.")
    if not str(data.get("title") or "").strip():
        errors.append("Заголовок обязателен.")
    if len(str(data.get("title") or "")) > 160:
        errors.append("Заголовок длиннее 160 символов.")
    for name in ("cause", "solution"):
        if len(str(data.get(name) or "")) > 2000:
            errors.append(f"Поле {name} длиннее 2000 символов.")

    patterns_all = data.get("patterns_all") or []
    patterns_any = data.get("patterns_any") or []
    exit_codes = data.get("exit_codes") or []
    if not patterns_all and not patterns_any and not exit_codes:
        errors.append("Нужен хотя бы один шаблон или код завершения — иначе правило ловит всё подряд.")
    for label, patterns in (("«все»", patterns_all), ("«любой»", patterns_any)):
        if len(patterns) > MAX_PATTERNS:
            errors.append(f"Шаблонов {label} больше {MAX_PATTERNS}.")
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                errors.append(f"Пустой шаблон в списке {label}.")
            elif len(pattern) > MAX_PATTERN_LEN:
                errors.append(f"Шаблон длиннее {MAX_PATTERN_LEN} символов: {pattern[:40]}…")
            elif _compile(pattern) is None:
                errors.append(f"Шаблон не компилируется: {pattern[:80]}")
    if any(not isinstance(code, int) for code in exit_codes):
        errors.append("Коды завершения должны быть целыми числами.")

    actions = data.get("actions") or []
    if len(actions) > MAX_ACTIONS:
        errors.append(f"Кнопок больше {MAX_ACTIONS}.")
    for action in actions:
        action_type = (action or {}).get("type")
        if action_type not in ACTION_TYPES:
            errors.append(f"Неизвестный тип кнопки: {action_type}.")
            continue
        if len(str(action.get("label") or "")) > 60:
            errors.append("Подпись кнопки длиннее 60 символов.")
        paths = action.get("paths") or []
        if action_type == "fix_files":
            if not paths:
                errors.append("Кнопке «Убрать файлы» нужен хотя бы один путь.")
            if len(paths) > MAX_PATHS:
                errors.append(f"У кнопки больше {MAX_PATHS} путей.")
            for path in paths:
                normalized = str(path).replace("\\", "/").strip().strip("/")
                if not normalized.startswith("config/") or ".." in normalized or ":" in normalized:
                    errors.append(f"Путь должен быть внутри config/: {path}")
        elif paths:
            errors.append(f"Пути задаются только для кнопки «Убрать файлы» (у «{action_type}» их быть не должно).")
    return errors


def effective_rules(session: Session, server: GameServer | None) -> list[dict[str, Any]]:
    """What the launcher of ``server`` ends up with: DB rules merged over the built-ins."""
    return merge_rules(load_builtin_rules(), rules_for_server(session, server))


def rules_for_server(session: Session, server: GameServer | None) -> list[dict[str, Any]]:
    """DB rules for a server (server-specific beats a global rule with the same key), disabled included."""
    stmt = select(LauncherCrashRule)
    if server is not None:
        stmt = stmt.where(or_(LauncherCrashRule.server_id.is_(None), LauncherCrashRule.server_id == server.id))
    else:
        stmt = stmt.where(LauncherCrashRule.server_id.is_(None))
    by_key: dict[str, LauncherCrashRule] = {}
    for rule in session.scalars(stmt.order_by(LauncherCrashRule.created_at)).all():
        current = by_key.get(rule.key)
        if current is None or (current.server_id is None and rule.server_id is not None):
            by_key[rule.key] = rule
    return [rule_to_dict(r) for r in by_key.values()]


def merge_rules(builtin: list[dict[str, Any]], remote: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror of CrashAdvisor.EffectiveRules: same key replaces, disabled removes, priority desc (stable)."""
    remote_by_key = {r["key"]: r for r in remote}
    merged = [remote_by_key.get(r["key"], r) for r in builtin]
    builtin_keys = {r["key"] for r in builtin}
    merged += [r for r in remote if r["key"] not in builtin_keys]
    merged = [r for r in merged if r.get("enabled", True)]
    return [r for _, r in sorted(enumerate(merged), key=lambda x: (-int(x[1].get("priority") or 0), x[0]))]


@dataclass
class MatchResult:
    matched: bool
    snippet: str | None = None
    captures: dict[str, str] = field(default_factory=dict)


def match_rule(rule: dict[str, Any], exit_code: int, haystack: str) -> MatchResult:
    exit_codes = rule.get("exit_codes") or []
    patterns_all = rule.get("patterns_all") or []
    patterns_any = rule.get("patterns_any") or []
    if exit_codes and exit_code not in exit_codes:
        return MatchResult(False)
    if not patterns_all and not patterns_any and not exit_codes:
        return MatchResult(False)

    snippet: str | None = None
    captures: dict[str, str] = {}

    def _try(pattern: str) -> bool:
        nonlocal snippet
        compiled = _compile(pattern)
        found = compiled.search(haystack) if compiled else None
        if not found:
            return False
        if snippet is None:
            start, end = max(0, found.start() - 60), min(len(haystack), found.end() + 60)
            snippet = haystack[start:end].strip()
        for name, value in found.groupdict().items():
            if value and name not in captures:
                captures[name] = value.strip()
        return True

    if not all(_try(p) for p in patterns_all):
        return MatchResult(False)
    if patterns_any:
        results = [_try(p) for p in patterns_any]  # no short-circuit: fill captures like the launcher
        if not any(results):
            return MatchResult(False)
    return MatchResult(True, snippet, captures)


def report_haystack(report: LauncherCrashReport) -> str:
    return (report.log_tail or "") + "\n" + (report.crash_report or "")


def classify_report(rules: list[dict[str, Any]], report: LauncherCrashReport) -> str | None:
    haystack = report_haystack(report)
    for rule in rules:
        if match_rule(rule, report.exit_code, haystack).matched:
            return rule["key"]
    return None
