from __future__ import annotations

import html
from email.utils import format_datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.models.nation import Nation
from apps.api.app.models.user import User

router = APIRouter(tags=["rss"])

SITE_URL = "https://void-rp.ru"
FEED_TITLE = "VoidRP — Государства Minecraft сервера"
FEED_DESCRIPTION = (
    "Новые государства на сервере VoidRP — Minecraft roleplay с живой экономикой и политикой."
)


@router.get("/rss.xml", include_in_schema=False)
def rss_feed(db: Session = Depends(get_db_session)) -> Response:
    nations = (
        db.execute(
            select(Nation)
            .join(User, User.id == Nation.leader_user_id)
            .where(Nation.is_public.is_(True))
            .where(User.is_admin.is_(False))
            .order_by(Nation.created_at.desc())
            .limit(30)
        )
        .scalars()
        .all()
    )

    items_xml = ""
    for nation in nations:
        title = html.escape(nation.title)
        link = f"{SITE_URL}/nation/{nation.slug}"
        desc = html.escape(nation.short_description or nation.title)
        pub_date = format_datetime(nation.created_at)
        guid = link

        items_xml += f"""
  <item>
    <title>{title}</title>
    <link>{link}</link>
    <description>{desc}</description>
    <pubDate>{pub_date}</pubDate>
    <guid isPermaLink="true">{guid}</guid>
  </item>"""

    build_date = format_datetime(nations[0].created_at) if nations else ""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{html.escape(FEED_TITLE)}</title>
    <link>{SITE_URL}</link>
    <description>{html.escape(FEED_DESCRIPTION)}</description>
    <language>ru</language>
    <lastBuildDate>{build_date}</lastBuildDate>
    <atom:link href="{SITE_URL}/rss.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>{SITE_URL}/logo.jpg</url>
      <title>{html.escape(FEED_TITLE)}</title>
      <link>{SITE_URL}</link>
    </image>
{items_xml}
  </channel>
</rss>"""

    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
