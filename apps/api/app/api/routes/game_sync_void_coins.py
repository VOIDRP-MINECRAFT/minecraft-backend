"""Void Coin (premium currency) — game-server-facing operations.

Void Coins are account-wide (stored on ``player_accounts``), so these endpoints
resolve the player by nickname globally and are guarded by the game-auth secret.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.dependencies.server_auth import require_game_auth_secret
from apps.api.app.models.player_account import PlayerAccount

router = APIRouter(
    prefix="/game-sync/void-coins",
    tags=["game-sync", "void-coins"],
    dependencies=[Depends(require_game_auth_secret)],
)


class VoidCoinGrant(BaseModel):
    nickname: str
    # Amount to add (may be negative to deduct/correct). Balance never goes below 0.
    amount: int = Field(..., ge=-1_000_000_000, le=1_000_000_000)


class VoidCoinBalance(BaseModel):
    nickname: str
    void_coins: int


def _resolve(db: Session, nickname: str) -> PlayerAccount:
    account = db.execute(
        select(PlayerAccount).where(
            PlayerAccount.minecraft_nickname_normalized == nickname.strip().lower()
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player account not found")
    return account


@router.post("/grant", response_model=VoidCoinBalance)
def grant_void_coins(payload: VoidCoinGrant, db: Annotated[Session, Depends(get_db_session)]) -> VoidCoinBalance:
    account = _resolve(db, payload.nickname)
    new_balance = int(account.void_coins or 0) + int(payload.amount)
    if new_balance < 0:
        new_balance = 0
    account.void_coins = new_balance
    db.commit()
    return VoidCoinBalance(nickname=account.minecraft_nickname, void_coins=new_balance)


@router.get("/{nickname}", response_model=VoidCoinBalance)
def get_void_coins(nickname: str, db: Annotated[Session, Depends(get_db_session)]) -> VoidCoinBalance:
    account = _resolve(db, nickname)
    return VoidCoinBalance(nickname=account.minecraft_nickname, void_coins=int(account.void_coins or 0))
