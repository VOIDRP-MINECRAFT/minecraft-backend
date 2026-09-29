"""What a sign-in looks like in «Активные входы»: browser and system from the
User-Agent, city from the IP (offline DB-IP City Lite — no requests to other services;
IP geolocation by DB-IP, CC BY 4.0)."""
from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from pathlib import Path

_GEO_DB = Path(__file__).resolve().parents[4] / "data" / "geo" / "dbip-city-lite.mmdb"

_CITY_RU = {
    "Moscow": "Москва", "Saint Petersburg": "Санкт-Петербург", "Novosibirsk": "Новосибирск",
    "Yekaterinburg": "Екатеринбург", "Kazan": "Казань", "Nizhniy Novgorod": "Нижний Новгород",
    "Nizhny Novgorod": "Нижний Новгород", "Chelyabinsk": "Челябинск", "Samara": "Самара", "Omsk": "Омск",
    "Rostov-on-Don": "Ростов-на-Дону", "Ufa": "Уфа", "Krasnoyarsk": "Красноярск", "Voronezh": "Воронеж",
    "Perm": "Пермь", "Volgograd": "Волгоград", "Krasnodar": "Краснодар", "Saratov": "Саратов",
    "Tyumen": "Тюмень", "Tolyatti": "Тольятти", "Izhevsk": "Ижевск", "Barnaul": "Барнаул",
    "Irkutsk": "Иркутск", "Khabarovsk": "Хабаровск", "Vladivostok": "Владивосток", "Yaroslavl": "Ярославль",
    "Tomsk": "Томск", "Orenburg": "Оренбург", "Kemerovo": "Кемерово", "Novokuznetsk": "Новокузнецк",
    "Ryazan": "Рязань", "Astrakhan": "Астрахань", "Penza": "Пенза", "Lipetsk": "Липецк", "Tula": "Тула",
    "Kaliningrad": "Калининград", "Sochi": "Сочи", "Minsk": "Минск", "Kyiv": "Киев", "Kiev": "Киев",
    "Almaty": "Алматы", "Astana": "Астана", "Tashkent": "Ташкент", "Bishkek": "Бишкек", "Tbilisi": "Тбилиси",
}


@lru_cache(maxsize=1)
def _reader():
    try:
        import maxminddb

        return maxminddb.open_database(str(_GEO_DB)) if _GEO_DB.exists() else None
    except Exception:  # noqa: BLE001 — no city is fine, nothing else depends on it
        return None


@lru_cache(maxsize=4096)
def locate(ip: str | None) -> str | None:
    """«Москва, Россия» — or None for a private/unknown address."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
        return "локальная сеть"
    reader = _reader()
    if reader is None:
        return None
    try:
        rec = reader.get(ip) or {}
    except Exception:  # noqa: BLE001
        return None
    city = ((rec.get("city") or {}).get("names") or {}).get("en")
    if city:
        city = re.sub(r"\s*\(.*\)$", "", city)
        city = _CITY_RU.get(city, city)
    names = (rec.get("country") or {}).get("names") or {}
    country = names.get("ru") or names.get("en")
    return ", ".join(x for x in (city, country) if x) or None


def describe(user_agent: str | None, device_name: str | None = None) -> dict:
    """{"browser": "Chrome 128", "os": "Windows", "kind": "desktop|mobile|tablet|app", "title": …}."""
    ua = user_agent or ""
    name = (device_name or "").strip()
    if "launcher" in name.lower() or "VoidRP-Launcher" in ua or "Electron" in ua:
        return {"browser": "Лаунчер VoidRP", "os": _os(ua), "kind": "app", "title": "Лаунчер VoidRP"}
    browser = _browser(ua)
    os_name = _os(ua)
    kind = "tablet" if re.search(r"iPad|Tablet", ua) else "mobile" if re.search(r"Mobile|Android|iPhone", ua) else "desktop"
    title = " · ".join(x for x in (browser, os_name) if x) or (name or "Неизвестное устройство")
    return {"browser": browser, "os": os_name, "kind": kind, "title": title}


def _browser(ua: str) -> str | None:
    for pattern, label in (
        (r"YaBrowser/(\d+)", "Яндекс Браузер"), (r"Edg/(\d+)", "Edge"), (r"OPR/(\d+)", "Opera"),
        (r"SamsungBrowser/(\d+)", "Samsung Internet"), (r"Firefox/(\d+)", "Firefox"),
        (r"Chrome/(\d+)", "Chrome"), (r"Version/(\d+)[\d.]* .*Safari", "Safari"),
    ):
        m = re.search(pattern, ua)
        if m:
            return f"{label} {m.group(1)}"
    return None


def _os(ua: str) -> str | None:
    if "Windows NT 10" in ua:
        return "Windows"
    if "Windows" in ua:
        return "Windows"
    m = re.search(r"Android (\d+)", ua)
    if m:
        return f"Android {m.group(1)}"
    m = re.search(r"(?:iPhone|iPad).*? OS (\d+)", ua)
    if m:
        return f"iOS {m.group(1)}"
    if "Mac OS X" in ua:
        return "macOS"
    if "CrOS" in ua:
        return "ChromeOS"
    if "Linux" in ua:
        return "Linux"
    return None
