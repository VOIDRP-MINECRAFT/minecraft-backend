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

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_market import PlayerMarketWebAction
from apps.api.app.models.void_upgrader import VoidUpgraderReward, VoidUpgraderSpin
from apps.api.app.models.void_upgrader_winning import VoidUpgraderWinning
from apps.api.app.models.void_upgrader_settings import VoidUpgraderSettings

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
        self._settings_cache: dict | None = None

    def settings(self) -> dict:
        """Per-server tunables; falls back to the module defaults when no row exists."""
        if self._settings_cache is None:
            row = self.session.execute(
                select(VoidUpgraderSettings).where(VoidUpgraderSettings.server_id == self.server_id)
            ).scalar_one_or_none()
            if row is None:
                self._settings_cache = {
                    "rtp": RTP, "coins_per_vc": COINS_PER_VC, "min_stake": MIN_STAKE,
                    "max_multiplier": MAX_MULTIPLIER, "max_chance": MAX_CHANCE,
                }
            else:
                self._settings_cache = {
                    "rtp": float(row.rtp), "coins_per_vc": int(row.coins_per_vc),
                    "min_stake": int(row.min_stake), "max_multiplier": float(row.max_multiplier),
                    "max_chance": float(row.max_chance),
                }
        return self._settings_cache

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

    def _enqueue_give(self, nickname: str, item_key: str, amount: int, display: str, give_command: str | None) -> None:
        self.session.add(
            PlayerMarketWebAction(
                server_id=self.server_id,
                player_name=nickname,
                action_type="give_reward",
                payload_json={
                    "item_key": item_key,
                    "amount": int(amount or 1),
                    "display": display,
                    "give_command": give_command,
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
        cfg = self.settings()
        stake = int(stake)
        balance = int(account.void_coins or 0)

        if stake < cfg["min_stake"]:
            raise VoidUpgraderError(f"Минимальная ставка — {cfg['min_stake']} Void Coin.")
        if stake > balance:
            raise VoidUpgraderError("Недостаточно Void Coin.")
        if stake >= int(reward.vc_value):
            raise VoidUpgraderError("Ставка должна быть меньше ценности награды — это апгрейд вверх.")

        multiplier = float(reward.vc_value) / float(stake)
        if multiplier > cfg["max_multiplier"]:
            raise VoidUpgraderError(
                f"Слишком большой множитель (макс ×{int(cfg['max_multiplier'])}). Повысь ставку или выбери награду дешевле."
            )
        win_chance = min(cfg["max_chance"], cfg["rtp"] / multiplier)

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

        # Stake is always spent up front. Atomic conditional decrement so two concurrent
        # spins can't double-spend the same balance (the WHERE re-checks under a row lock).
        row = self.session.execute(
            update(PlayerAccount)
            .where(PlayerAccount.user_id == account.user_id, PlayerAccount.void_coins >= stake)
            .values(void_coins=PlayerAccount.void_coins - stake)
            .returning(PlayerAccount.void_coins)
        ).first()
        if row is None:
            self.session.rollback()
            raise VoidUpgraderError("Недостаточно Void Coin.")
        new_balance = int(row[0])
        self.session.expire(account, ["void_coins"])   # ORM value is now stale

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
            # Item goes to the player's Upgrader inventory — they later CLAIM it in-game or SELL it for VC.
            self.session.add(VoidUpgraderWinning(
                server_id=self.server_id, user_id=account.user_id,
                minecraft_nickname=account.minecraft_nickname,
                item_key=reward.item_key, display_name=reward.display_name,
                vc_value=int(reward.vc_value), amount=int(reward.amount or 1),
                tier=reward.tier, give_command=reward.give_command,
            ))

        self.session.commit()

        return {
            "won": won,
            "roll": round(roll, 6),
            "win_chance": round(win_chance, 6),
            "multiplier": round(multiplier, 4),
            "stake": stake,
            "new_void_coins": new_balance,
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

    # ── winnings inventory (claim in-game / sell for Void Coin) ──────────────────
    def winnings(self, user_id: UUID) -> list[VoidUpgraderWinning]:
        return list(
            self.session.execute(
                select(VoidUpgraderWinning)
                .where(VoidUpgraderWinning.server_id == self.server_id, VoidUpgraderWinning.user_id == user_id)
                .order_by(VoidUpgraderWinning.created_at.desc())
            ).scalars().all()
        )

    def _winning(self, user_id: UUID, winning_id: UUID) -> VoidUpgraderWinning:
        w = self.session.execute(
            select(VoidUpgraderWinning).where(
                VoidUpgraderWinning.id == winning_id,
                VoidUpgraderWinning.server_id == self.server_id,
                VoidUpgraderWinning.user_id == user_id,
            )
        ).scalar_one_or_none()
        if w is None:
            raise VoidUpgraderError("Выигрыш не найден.")
        return w

    def claim(self, account: PlayerAccount, winning_id: UUID) -> dict:
        w = self._winning(account.user_id, winning_id)
        self._enqueue_give(account.minecraft_nickname, w.item_key, int(w.amount or 1), w.display_name, w.give_command)
        item = {"item_key": w.item_key, "display_name": w.display_name, "amount": int(w.amount or 1)}
        self.session.delete(w)
        self.session.commit()
        return item

    def sell(self, account: PlayerAccount, winning_id: UUID) -> dict:
        w = self._winning(account.user_id, winning_id)
        vc = int(w.vc_value)
        row = self.session.execute(
            update(PlayerAccount)
            .where(PlayerAccount.user_id == account.user_id)
            .values(void_coins=PlayerAccount.void_coins + vc)
            .returning(PlayerAccount.void_coins)
        ).first()
        new_balance = int(row[0]) if row else vc
        self.session.expire(account, ["void_coins"])
        self.session.delete(w)
        self.session.commit()
        return {"vc_value": vc, "new_void_coins": new_balance, "display_name": w.display_name}

    def recent_wins(self, limit: int = 15) -> list[VoidUpgraderSpin]:
        """Latest winning spins on this server (public 'recent drops' feed)."""
        return list(
            self.session.execute(
                select(VoidUpgraderSpin)
                .where(
                    VoidUpgraderSpin.server_id == self.server_id,
                    VoidUpgraderSpin.won.is_(True),
                )
                .order_by(VoidUpgraderSpin.created_at.desc())
                .limit(limit)
            ).scalars().all()
        )

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
