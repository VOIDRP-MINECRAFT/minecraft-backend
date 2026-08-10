from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.news import NewsPost

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Cyrillic → latin for readable slugs.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def _slugify(title: str) -> str:
    text = "".join(_TRANSLIT.get(ch, ch) for ch in title.lower())
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = _SLUG_RE.sub("-", text).strip("-")
    return text[:180] or "post"


def _strip_markdown(text: str, limit: int = 500) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)       # links → text
    text = re.sub(r"[#*_>`~]", "", text)                        # md symbols
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:limit]


def _build_opener() -> urllib.request.OpenerDirector:
    # This host has no direct egress; route external calls through the configured
    # proxy when set (falls back to a direct opener otherwise).
    proxy = get_settings().outbound_proxy_url
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def _http_post_json(url: str, payload: dict, timeout: float = 8.0) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with _build_opener().open(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False


class NewsService:
    def __init__(self, session: Session, server: GameServer) -> None:
        self.session = session
        self.server = server
        self.server_id: UUID = server.id

    # ── slug ────────────────────────────────────────────────────────────────
    def _unique_slug(self, title: str) -> str:
        base = _slugify(title)
        slug = base
        i = 2
        while self.session.scalar(
            select(NewsPost.id).where(
                NewsPost.server_id == self.server_id, NewsPost.slug == slug
            )
        ):
            slug = f"{base}-{i}"
            i += 1
        return slug

    # ── queries ─────────────────────────────────────────────────────────────
    def list_public(self, limit: int, offset: int, category: str | None = None) -> tuple[list[NewsPost], int]:
        base = select(NewsPost).where(
            NewsPost.server_id == self.server_id, NewsPost.is_published.is_(True)
        )
        if category:
            base = base.where(NewsPost.category == category)
        total = self.session.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0
        rows = self.session.scalars(
            base.order_by(NewsPost.published_at.desc().nullslast(), NewsPost.created_at.desc())
            .limit(limit).offset(offset)
        ).all()
        return list(rows), int(total)

    def get_public_by_slug(self, slug: str) -> NewsPost | None:
        return self.session.scalar(
            select(NewsPost).where(
                NewsPost.server_id == self.server_id,
                NewsPost.slug == slug,
                NewsPost.is_published.is_(True),
            )
        )

    def list_admin(self, limit: int, offset: int, category: str | None = None) -> tuple[list[NewsPost], int]:
        base = select(NewsPost).where(NewsPost.server_id == self.server_id)
        if category:
            base = base.where(NewsPost.category == category)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.scalars(
            base.order_by(NewsPost.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), int(total)

    def get_by_id(self, post_id: UUID) -> NewsPost | None:
        post = self.session.get(NewsPost, post_id)
        if post is None or post.server_id != self.server_id:
            return None
        return post

    # ── mutations ─────────────────────────────────────────────────────────────
    def create(self, *, category, title, summary, body, cover_image_url, is_published, author) -> NewsPost:
        post = NewsPost(
            server_id=self.server_id,
            category=category,
            title=title,
            slug=self._unique_slug(title),
            summary=summary,
            body=body or "",
            cover_image_url=cover_image_url,
            is_published=is_published,
            published_at=datetime.now(timezone.utc) if is_published else None,
            author_id=getattr(author, "id", None),
            author_name=getattr(author, "site_login", None) or getattr(author, "email", None),
        )
        self.session.add(post)
        self.session.flush()
        return post

    def update(self, post: NewsPost, data: dict) -> NewsPost:
        for field in ("title", "summary", "body", "cover_image_url"):
            if field in data and data[field] is not None:
                setattr(post, field, data[field])
        if "is_published" in data and data["is_published"] is not None:
            newly = data["is_published"] and not post.is_published
            post.is_published = data["is_published"]
            if newly and post.published_at is None:
                post.published_at = datetime.now(timezone.utc)
        self.session.flush()
        return post

    def delete(self, post: NewsPost) -> None:
        self.session.delete(post)

    # ── broadcast (Telegram + Discord) ────────────────────────────────────────
    def _post_url(self, post: NewsPost) -> str:
        base = get_settings().website_base_url.rstrip("/")
        return f"{base}/news/{post.slug}?server={self.server.slug}"

    def broadcast(self, post: NewsPost, *, to_telegram: bool, to_discord: bool) -> dict:
        result: dict = {"telegram_ok": None, "discord_ok": None}
        url = self._post_url(post)
        excerpt = post.summary or _strip_markdown(post.body, 400)
        # Channels are per news category (update/media).
        channels = self.server.channels_for(post.category)

        if to_telegram:
            token = get_settings().telegram_bot_token
            targets = channels["telegram"]
            if token and targets:
                text = f"<b>{_esc(post.title)}</b>"
                if excerpt:
                    text += f"\n\n{_esc(excerpt)}"
                text += f'\n\n<a href="{url}">Читать на сайте →</a>'
                any_ok = False
                for t in targets:
                    chat = (t or {}).get("chat_id")
                    if not chat:
                        continue
                    payload = {
                        "chat_id": chat, "text": text, "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                    }
                    # Forum-topic supergroup: post into this target's own topic.
                    thread = (t or {}).get("thread_id")
                    if thread:
                        payload["message_thread_id"] = thread
                    if _http_post_json(f"https://api.telegram.org/bot{token}/sendMessage", payload):
                        any_ok = True
                result["telegram_ok"] = any_ok
                if any_ok:
                    post.posted_telegram = True
            else:
                result["telegram_ok"] = False

        if to_discord:
            webhooks = channels["discord"]
            if webhooks:
                embed = {"title": post.title[:256], "url": url, "color": 0x7C3AED}
                if excerpt:
                    embed["description"] = excerpt[:2000]
                if post.cover_image_url:
                    embed["image"] = {"url": post.cover_image_url}
                any_ok = False
                for hook in webhooks:
                    if hook and _http_post_json(hook, {"embeds": [embed]}):
                        any_ok = True
                result["discord_ok"] = any_ok
                if any_ok:
                    post.posted_discord = True
            else:
                result["discord_ok"] = False

        self.session.flush()
        return result


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
