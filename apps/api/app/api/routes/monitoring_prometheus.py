"""Prometheus scrape endpoint for the shared Grafana/Prometheus stack.

GET {api_v1_prefix}/monitoring/prometheus

Disabled (404) unless ``PROMETHEUS_SCRAPE_TOKEN`` is set, and then it requires
``Authorization: Bearer <token>`` — matching a Prometheus scrape job's
``authorization.credentials``. This keeps online-player counts and server
internals from leaking on an unauthenticated public endpoint.
"""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import PlainTextResponse

from apps.api.app.config import get_settings
from apps.api.app.core import prometheus_exporter

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

# Prometheus text exposition format v0.0.4.
_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/prometheus", include_in_schema=False)
def prometheus_metrics(
    authorization: Annotated[str | None, Header()] = None,
) -> PlainTextResponse:
    settings = get_settings()
    token = settings.prometheus_scrape_token
    if not token:
        # Endpoint intentionally off until a token is configured.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not hmac.compare_digest(presented, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    text = prometheus_exporter.render_metrics(ttl=settings.prometheus_cache_ttl_seconds)
    return PlainTextResponse(content=text, media_type=_CONTENT_TYPE)
