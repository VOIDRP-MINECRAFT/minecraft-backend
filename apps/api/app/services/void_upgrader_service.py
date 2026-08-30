"""Void Upgrader service — server-authoritative spin logic.

The player stakes Void Coins and targets a reward worth more than the stake; the win
chance is ``RTP * stake / reward_value`` (i.e. RTP / multiplier). On a win the reward
item is delivered in-game via the existing web-action queue; the stake is always spent.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_market import PlayerMarketWebAction
from apps.api.app.models.void_upgrader import VoidUpgraderReward, VoidUpgraderSpin

# Tunables (v1 constants; move to config later if needed).
COINS_PER_VC = 1000       # 1 Void Coin == this many in-game coins (used only by the seeder)
RTP = 0.90                # return-to-player; house edge = 1 - RTP
MIN_STAKE = 1
MAX_MULTIPLIER = 100.0    # cap variance: reward may be at most 100x the stake
MAX_CHANCE = 0.90         # even a near-value upgrade keeps at least 10% risk


class VoidUpgraderError(Exception):
    """User-facing validation error (mapped to HTTP 400)."""


class VoidUpgraderService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    def rewards(self) -> list[VoidUpgraderReward]:
        return list(
            self.session.execute(
                select(VoidUpgraderReward)
                .where(
                    VoidUpgraderReward.server_id == self.server_id,
                    VoidUpgraderReward.enabled.is_(True),
                )
                .order_by(VoidUpgraderReward.vc_value)
            ).scalars().all()
        )

    def _reward(self, reward_id: UUID) -> VoidUpgraderReward:
        reward = self.session.execute(
            select(VoidUpgraderReward).where(
                VoidUpgraderReward.id == reward_id,
                VoidUpgraderReward.server_id == self.server_id,
                VoidUpgraderReward.enabled.is_(True),
            )
        ).scalar_one_or_none()
        if reward is None:
            raise VoidUpgraderError("Награда не найдена.")
        return reward

    def _enqueue_give(self, nickname: str, reward: VoidUpgraderReward) -> None:
        self.session.add(
            PlayerMarketWebAction(
                server_id=self.server_id,
                player_name=nickname,
                action_type="give_reward",
                payload_json={
                    "item_key": reward.item_key,
                    "amount": int(reward.amount or 1),
                    "display": reward.display_name,
                    "give_command": reward.give_command,
                    "source": "upgrader",
                },
                status="pending",
            )
        )

    def spin(
        self,
        account: PlayerAccount,
        reward_id: UUID,
        stake: int,
        client_seed: str | None = None,
    ) -> dict:
        reward = self._reward(reward_id)
        stake = int(stake)
        balance = int(account.void_coins or 0)

        if stake < MIN_STAKE:
            raise VoidUpgraderError(f"Минимальная ставка — {MIN_STAKE} Void Coin.")
        if stake > balance:
            raise VoidUpgraderError("Недостаточно Void Coin.")
        if stake >= int(reward.vc_value):
            raise VoidUpgraderError("Ставка должна быть меньше ценности награды — это апгрейд вверх.")

        multiplier = float(reward.vc_value) / float(stake)
        if multiplier > MAX_MULTIPLIER:
            raise VoidUpgraderError(
                f"Слишком большой множитель (макс ×{int(MAX_MULTIPLIER)}). Повысь ставку или выбери награду дешевле."
            )
        win_chance = min(MAX_CHANCE, RTP / multiplier)

        # Server-authoritative RNG (provably-fair-lite: seeds stored per spin).
        server_seed = secrets.token_hex(16)
        client_seed = (client_seed or secrets.token_hex(8))[:64]
        nonce = int(
            self.session.execute(
                select(func.count(VoidUpgraderSpin.id)).where(
                    VoidUpgraderSpin.server_id == self.server_id,
                    VoidUpgraderSpin.user_id == account.user_id,
                )
            ).scalar_one()
        )
        digest = hmac.new(server_seed.encode(), f"{client_seed}:{nonce}".encode(), hashlib.sha256).hexdigest()
        roll = int(digest[:15], 16) / float(16 ** 15)   # uniform in [0, 1)
        won = roll < win_chance

        # Stake is always spent up front.
        account.void_coins = balance - stake

        self.session.add(
            VoidUpgraderSpin(
                server_id=self.server_id,
                user_id=account.user_id,
                minecraft_nickname=account.minecraft_nickname,
                stake=stake,
                reward_item_key=reward.item_key,
                reward_display=reward.display_name,
                reward_vc_value=int(reward.vc_value),
                multiplier=multiplier,
                win_chance=win_chance,
                roll=roll,
                won=won,
                server_seed=server_seed,
                client_seed=client_seed,
                nonce=nonce,
            )
        )

        if won:
            self._enqueue_give(account.minecraft_nickname, reward)

        self.session.commit()

        return {
            "won": won,
            "roll": round(roll, 6),
            "win_chance": round(win_chance, 6),
            "multiplier": round(multiplier, 4),
            "stake": stake,
            "new_void_coins": int(account.void_coins),
            "reward": {
                "id": str(reward.id),
                "item_key": reward.item_key,
                "display_name": reward.display_name,
                "image_url": reward.image_url,
                "vc_value": int(reward.vc_value),
                "amount": int(reward.amount or 1),
                "tier": reward.tier,
            },
            "server_seed_hash": hashlib.sha256(server_seed.encode()).hexdigest(),
            "client_seed": client_seed,
            "nonce": nonce,
        }

    def history(self, user_id: UUID, limit: int = 20) -> list[VoidUpgraderSpin]:
        return list(
            self.session.execute(
                select(VoidUpgraderSpin)
                .where(
                    VoidUpgraderSpin.server_id == self.server_id,
                    VoidUpgraderSpin.user_id == user_id,
                )
                .order_by(VoidUpgraderSpin.created_at.desc())
                .limit(limit)
            ).scalars().all()
        )
