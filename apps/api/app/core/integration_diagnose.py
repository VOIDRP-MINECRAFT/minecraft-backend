"""«Почему?»: the evidence about a server turned into causes and steps, in plain words.

Reads the same overview the page has — plugin reports, the outside ping, the inventory, the
doctor's report, the secret, uptime and TPS — and orders what it finds by how much it hurts.
Rules, not guesses: every finding names the fact it comes from.
"""
from __future__ import annotations

from typing import Any


def _f(severity: str, title: str, cause: str, steps: list[str]) -> dict[str, Any]:
    return {"severity": severity, "title": title, "cause": cause, "steps": steps}


def diagnose(data: dict[str, Any]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    api = data.get("api_url") or "https://api.void-rp.ru"
    reports = data.get("reports") or []
    fresh = [r for r in reports if r.get("fresh")]
    reach = data.get("reach") or {}
    reachable = reach.get("ok") is True
    unreachable = reach.get("ok") is False and reach.get("address")

    if not reports:
        out.append(_f("err", "Сервер ещё не подключён",
                      "Ни один плагин VoidRP не прислал отчёт.",
                      ["Вкладка «Установка» → «Одной командой»: скрипт поставит плагины и конфиги.",
                       "После запуска сервера отчёт приходит меньше чем за минуту."]))
    elif not fresh:
        if reachable:
            out.append(_f("err", "Сервер работает, но не достучался до VoidRP",
                          f"Снаружи он отвечает ({reach.get('players', 0)} игроков, {reach.get('version')}), "
                          "а отчётов от плагинов нет — значит, плагины не могут связаться с панелью.",
                          [f"В логе сервера найдите строки VoidRpPerms/VoidRpAuth: «HTTP 401» — неверный секрет "
                           "(возьмите свежие конфиги), «ConnectException»/«timed out» — закрыт исходящий доступ.",
                           f"Разрешите серверу исходящие соединения на {api} (порт 443).",
                           "Запустите проверку сервера с --send (вкладка «Сервер») — она найдёт причину."]))
        else:
            why = reach.get("error") if unreachable else "сервер не отвечает"
            out.append(_f("err", "Сервер выключен или недоступен",
                          f"Отчётов от плагинов нет, и снаружи сервер {why}.",
                          ["Проверьте в панели хостинга, запущен ли сервер и нет ли ошибки при старте.",
                           "Если запущен — проверьте, открыт ли игровой порт и верен ли адрес в «Серверах»."]))
    else:
        for r in data.get("required") or []:
            if not r.get("ok"):
                hint = ("VoidRpAuth (вход по аккаунту VoidRP)" if r.get("key") == "auth"
                        else "VoidRpPerms 0.4.0+ (мониторинг)")
                out.append(_f("err", f"Не работает: {r.get('label')}",
                              "Другие плагины отчитываются, а этот модуль — нет: плагин не установлен, старый или "
                              "выключился с ошибкой.",
                              [f"Поставьте или обновите {hint} — вкладка «Плагины».",
                               "Посмотрите в логе сервера ошибки этого плагина при запуске."]))
        if unreachable:
            out.append(_f("err", "Игроки не могут зайти снаружи",
                          f"Плагины работают, но адрес {reach.get('address')} {reach.get('error')}.",
                          ["Откройте игровой порт на хостинге/фаерволе.",
                           "Проверьте, что адрес и порт в «Серверах» те же, что у игроков.",
                           "Если сервер за прокси (Velocity/Bungee) — в «Серверах» должен быть адрес прокси."]))

    st = data.get("status") or {}
    tps = [p["tps"] for p in st.get("series_24h") or [] if p.get("tps") is not None]
    if tps and min(tps[-4:] or tps) < 15:
        out.append(_f("warn", "Сервер тормозит",
                      f"TPS за последний час опускался до {min(tps[-4:] or tps):.1f} (норма — 20).",
                      ["Снимите профиль: /spark profiler start, через пару минут /spark profiler stop.",
                       "Частые причины: большая дальность прорисовки, фермы мобов, тяжёлые плагины, мало памяти."]))
    for it in data.get("items") or []:
        if it.get("kind") != "ours":
            continue
        if it.get("unsupported"):
            out.append(_f("err", f"{it['name']} {it['installed']['version']} больше не поддерживается",
                          f"Минимальная версия — {it.get('min_supported')}.{(' ' + it['support_note']) if it.get('support_note') else ''}",
                          ["Скачайте свежую сборку во вкладке «Плагины» или включите автообновление."]))
        elif it.get("outdated"):
            out.append(_f("info", f"Есть обновление {it['name']}",
                          f"На сервере {it['installed']['version']}, вышла {it['latest']['version']}.",
                          ["Включите автообновление — новая версия встанет при перезапуске."]))
    for x in (data.get("inventory") or {}).get("issues") or []:
        if x.get("level") in ("err", "warn"):
            out.append(_f(x["level"], "Найдено на сервере", x["text"], []))
    sec = data.get("secret") or {}
    if sec.get("old_secret_plugins"):
        out.append(_f("warn", "Плагины на старом секрете",
                      f"{', '.join(sec['old_secret_plugins'])} ещё подключаются старым секретом.",
                      ["Перезапустите сервер до окончания действия старого секрета."]))
    doctor = (data.get("doctor") or {}).get("text") or ""
    for line in doctor.splitlines():
        if line.startswith("[!!]"):
            out.append(_f("warn", "Проверка сервера", line[4:].strip(), []))

    order = {"err": 0, "warn": 1, "info": 2}
    out.sort(key=lambda f: order.get(f["severity"], 3))
    if not out:
        headline = "Проблем не нашёл: сервер на связи, модули работают, снаружи доступен."
    else:
        headline = out[0]["title"]
    return {"headline": headline, "findings": out}
