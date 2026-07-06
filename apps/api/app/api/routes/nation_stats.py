from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.auth import get_current_user
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.user import User
from apps.api.app.schemas.nation_stats import (
    NationDonorListResponse,
    NationMemberStatsSyncRequest,
    NationMemberStatsSyncResponse,
    NationRankingResponse,
    NationStatsRead,
    NationStatsUpsertRequest,
    NationStatsUpsertResponse,
    NationTreasuryActionResponse,
    NationTreasuryDepositRequest,
    NationTreasuryPlayerDonateInternalRequest,
    NationTreasuryPlayerWithdrawInternalRequest,
    NationTreasuryTransactionListResponse,
    NationTreasuryWithdrawRequest,
    PlayerStatCacheSyncRequest,
    PlayerStatCacheSyncResponse,
)
from apps.api.app.services.nation_service import NationNotFoundError
from apps.api.app.services.nation_stats_service import (
    NationStatsPermissionError,
    NationStatsService,
    NationStatsValidationError,
)

router = APIRouter(prefix="/nation-stats", tags=["nation-stats"])


def get_stats_service(
    session: Annotated[Session, Depends(get_db_session)],
    server: Annotated[GameServer, Depends(resolve_server)],
) -> NationStatsService:
    return NationStatsService(session, server.id)


@router.get("/nations/{slug}", response_model=NationStatsRead)
def get_nation_stats(
    slug: str,
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationStatsRead:
    try:
        return service.get_stats_by_slug(slug)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/rankings", response_model=NationRankingResponse)
def get_nation_rankings(
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationRankingResponse:
    return service.get_rankings()


@router.post("/internal/upsert", response_model=NationStatsUpsertResponse)
def internal_upsert_nation_stats(
    payload: NationStatsUpsertRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationStatsUpsertResponse:
    try:
        return service.upsert_from_game(payload)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/internal/member-snapshots/upsert", response_model=NationMemberStatsSyncResponse)
def internal_upsert_nation_member_snapshots(
    payload: NationMemberStatsSyncRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationMemberStatsSyncResponse:
    try:
        return service.upsert_member_snapshots_from_game(payload)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NationStatsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/internal/player-stats/upsert", response_model=PlayerStatCacheSyncResponse)
def internal_upsert_player_stats_cache(
    payload: PlayerStatCacheSyncRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> PlayerStatCacheSyncResponse:
    return service.upsert_player_stats_cache(payload)


@router.post("/internal/player-donate", response_model=NationTreasuryActionResponse)
def internal_player_donate_to_nation_treasury(
    payload: NationTreasuryPlayerDonateInternalRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationTreasuryActionResponse:
    try:
        return service.donate_from_game_player(
            nation_slug=payload.nation_slug,
            amount=payload.amount,
            minecraft_nickname=payload.minecraft_nickname,
            comment=payload.comment,
        )
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NationStatsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/internal/player-withdraw", response_model=NationTreasuryActionResponse)
def internal_player_withdraw_from_nation_treasury(
    payload: NationTreasuryPlayerWithdrawInternalRequest,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationTreasuryActionResponse:
    try:
        return service.withdraw_from_game_player(
            nation_slug=payload.nation_slug,
            amount=payload.amount,
            minecraft_nickname=payload.minecraft_nickname,
            comment=payload.comment,
        )
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NationStatsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/internal/nations/{slug}/summary", response_model=NationStatsRead)
def internal_get_nation_treasury_summary(
    slug: str,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationStatsRead:
    try:
        return service.get_stats_by_slug(slug)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/internal/nations/{slug}/transactions", response_model=NationTreasuryTransactionListResponse)
def internal_get_nation_treasury_transactions(
    slug: str,
    _: Annotated[None, Depends(require_game_auth_secret)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationTreasuryTransactionListResponse:
    try:
        return service.list_transactions_for_nation(slug)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/nations/{slug}/deposit", response_model=NationTreasuryActionResponse)
def deposit_nation_treasury(
    slug: str,
    payload: NationTreasuryDepositRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationTreasuryActionResponse:
    try:
        return service.deposit(
            current_user=current_user,
            nation_slug=slug,
            amount=payload.amount,
            comment=payload.comment,
        )
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NationStatsPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NationStatsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/nations/{slug}/withdraw", response_model=NationTreasuryActionResponse)
def withdraw_nation_treasury(
    slug: str,
    payload: NationTreasuryWithdrawRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationTreasuryActionResponse:
    try:
        return service.withdraw(
            current_user=current_user,
            nation_slug=slug,
            amount=payload.amount,
            comment=payload.comment,
        )
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NationStatsPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NationStatsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/nations/{slug}/transactions", response_model=NationTreasuryTransactionListResponse)
def list_nation_treasury_transactions(
    slug: str,
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationTreasuryTransactionListResponse:
    try:
        return service.list_transactions_for_nation(slug)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/nations/treasury-tax")
def apply_treasury_tax(
    payload: dict,
    service: Annotated[NationStatsService, Depends(get_stats_service)],
    _: Annotated[None, Depends(require_game_auth_secret)],
) -> dict:
    rate = float(payload.get("rate", 0.05))
    try:
        return service.apply_treasury_tax(rate)
    except NationStatsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/nations/{slug}/donors", response_model=NationDonorListResponse)
def list_nation_top_donors(
    slug: str,
    service: Annotated[NationStatsService, Depends(get_stats_service)],
) -> NationDonorListResponse:
    try:
        return service.list_top_donors_for_nation(slug)
    except NationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
