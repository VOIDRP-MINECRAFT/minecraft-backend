from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from apps.api.app.config import get_settings
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.services.easydonate_service import EasyDonateError, EasyDonateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/donate", tags=["donate"])


def get_donate_service(
    server: Annotated[GameServer, Depends(resolve_server)],
) -> EasyDonateService:
    # Scope products/payment to the active server's EasyDonate shop so commands
    # are delivered to that server; falls back to the global default when unset.
    return EasyDonateService(settings=get_settings(), server_id=server.easydonate_server_id)


class PaymentCreateRequest(BaseModel):
    products: dict[int, int]
    coupon: str | None = None


class DonateCallbackPayload(BaseModel):
    payment_id: int
    shop_id: int
    customer: str
    email: str | None = None
    cost: float
    income: float
    products: list
    signature: str


@router.get("/products")
def list_products(service: Annotated[EasyDonateService, Depends(get_donate_service)]):
    try:
        return service.get_products()
    except EasyDonateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)


@router.get("/products/{product_id}")
def get_product(
    product_id: int,
    service: Annotated[EasyDonateService, Depends(get_donate_service)],
):
    try:
        return service.get_product(product_id)
    except EasyDonateError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)


@router.get("/servers")
def list_servers(service: Annotated[EasyDonateService, Depends(get_donate_service)]):
    try:
        return service.get_servers()
    except EasyDonateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)


@router.get("/payments/last")
def last_payments(service: Annotated[EasyDonateService, Depends(get_donate_service)]):
    try:
        return service.get_last_payments()
    except EasyDonateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)


@router.post("/payment")
def create_payment(
    payload: PaymentCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[EasyDonateService, Depends(get_donate_service)],
):
    if not current_user.player_account or not current_user.player_account.minecraft_nickname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minecraft nickname not linked to account",
        )
    nickname = current_user.player_account.minecraft_nickname
    settings = get_settings()
    success_url = f"{settings.website_base_url}/shop?success=1"
    try:
        result = service.create_payment(
            customer=nickname,
            products=payload.products,
            email=current_user.email,
            coupon=payload.coupon,
            success_url=success_url,
        )
        return {"url": result.get("url") or result.get("payment_url") or result}
    except EasyDonateError as exc:
        logger.error("EasyDonate payment error code=%s message=%s", exc.code, exc.message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


@router.post("/callback", status_code=status.HTTP_200_OK)
async def callback(request: Request, service: Annotated[EasyDonateService, Depends(get_donate_service)]):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    payload = DonateCallbackPayload(**body)

    if not service.verify_callback_signature(
        payment_id=payload.payment_id,
        cost=payload.cost,
        customer=payload.customer,
        signature=payload.signature,
    ):
        logger.warning("EasyDonate callback: invalid signature for payment_id=%s", payload.payment_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    product_names = [p.get("name", str(p.get("id", "?"))) for p in payload.products]
    logger.info(
        "DONATE | payment_id=%s customer=%s cost=%.2f products=%s",
        payload.payment_id,
        payload.customer,
        payload.cost,
        product_names,
    )

    return {"ok": True}