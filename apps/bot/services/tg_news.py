from __future__ import annotations

import re
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

from apps.api.app.config import get_settings

# ── Telegram entities → Markdown (for the site news body) ────────────────────
# Telegram entity offsets/lengths are in UTF-16 code units, so we index the text
# as UTF-16 to place the markers correctly (emoji / non-BMP safe).


def _markers(entity) -> tuple[str, str] | None:
    t = str(getattr(entity, "type", ""))
    if t == "bold":
        return ("**", "**")
    if t == "italic":
        return ("*", "*")
    if t == "underline":
        return ("<u>", "</u>")
    if t == "strikethrough":
        return ("~~", "~~")
    if t == "code":
        return ("`", "`")
    if t == "pre":
        return ("\n```\n", "\n```\n")
    if t == "blockquote":
        return ("> ", "")
    if t == "text_link":
        url = getattr(entity, "url", None)
        if url:
            return ("[", f"]({url})")
    return None


def entities_to_markdown(text: str | None, entities: list | None) -> str:
    if not text:
        return ""
    if not entities:
        return text
    # Assemble in UTF-16-LE bytes and decode once at the end — decoding single
    # code units would split surrogate pairs (emoji / non-BMP) and crash.
    buf = text.encode("utf-16-le")
    n = len(buf) // 2
    opens: dict[int, list[bytes]] = defaultdict(list)
    closes: dict[int, list[bytes]] = defaultdict(list)
    for e in entities:
        mk = _markers(e)
        if mk is None:
            continue
        pre, suf = mk
        start = int(e.offset)
        end = start + int(e.length)
        if start < 0 or end > n:
            continue
        opens[start].append(pre.encode("utf-16-le"))
        closes[end].append(suf.encode("utf-16-le"))
    out = bytearray()
    for i in range(n + 1):
        for suf in reversed(closes.get(i, [])):
            out += suf
        for pre in opens.get(i, []):
            out += pre
        if i < n:
            out += buf[i * 2:i * 2 + 2]
    return out.decode("utf-16-le", errors="replace")


def make_excerpt(text: str | None, limit: int = 300) -> str | None:
    if not text:
        return None
    clean = re.sub(r"\s+", " ", text).strip()
    return (clean[:limit] or None) if clean else None


def make_title(text: str | None, fallback: str = "Новость") -> str:
    """Derive a default title from the first line of the message."""
    if not text:
        return fallback
    first = text.strip().splitlines()[0].strip()
    return (first[:120] or fallback)


# ── Cover image: save a Telegram photo (bytes) as a 16:6 WebP banner ─────────
def save_cover_from_bytes(data: bytes) -> str | None:
    """Center-crop to 1600×600 and store under media/news; return public URL.
    Mirrors the admin news cover-upload behaviour."""
    settings = get_settings()
    try:
        img = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None
    target_w, target_h = 1600, 600
    ratio = target_w / target_h
    w, h = img.size
    if w / h > ratio:
        new_w = int(h * ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    img = img.resize((target_w, target_h), Image.LANCZOS)

    rel_dir = Path("news")
    abs_dir = Path(settings.media_storage_root) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.webp"
    img.save(abs_dir / filename, format="WEBP", quality=88, method=4)
    return f"{settings.media_public_base_url.rstrip('/')}/{(rel_dir / filename).as_posix()}"
