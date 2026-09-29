from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.app.config import get_settings
from apps.api.app.dependencies.admin import require_permission
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.services.easydonate_service import EasyDonateError, EasyDonateService

router = APIRouter(
    prefix="/admin/donate",
    tags=["admin", "donate"],
    dependencies=[Depends(require_permission("donate.view"))],
)


def get_service(server: Annotated[GameServer, Depends(resolve_server)]) -> EasyDonateService:
    """The shop of the server chosen in the admin panel: its own key; the global key only
    for the default server."""
    service = EasyDonateService.for_server(server, get_settings())
    if not service.configured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Donations are not set up for this server")
    return service


@router.get("/overview")
def get_overview(service: Annotated[EasyDonateService, Depends(get_service)]) -> dict:
    """Returns stats + first-page payments + products + chart data in one cached call."""
    try:
        return service.get_admin_overview()
    except EasyDonateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)


@router.get("/payments")
def get_payments(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    service: Annotated[EasyDonateService, Depends(get_service)] = None,
) -> dict:
    assert service is not None
    try:
        return service.get_payments_paginated(page=page, per_page=per_page)
    except EasyDonateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)
