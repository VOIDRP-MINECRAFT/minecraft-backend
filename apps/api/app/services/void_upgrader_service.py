"""Void Upgrader service — server-authoritative spin logic.

The player stakes Void Coins and targets a reward worth more than the stake; the win
chance is ``RTP * stake / reward_value`` (i.e. RTP / multiplier). On a win the reward
item is delivered in-game via the existing web-action queue; the stake is always spent.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Integer, case, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.api.app.models.battlepass import BattlePassProgress
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.player_market import PlayerMarketWebAction
from apps.api.app.models.void_upgrader import VoidUpgraderReward, VoidUpgraderSpin
from apps.api.app.models.void_upgrader_daily import VoidUpgraderDaily
from apps.api.app.models.void_upgrader_jackpot import VoidUpgraderJackpot
from apps.api.app.models.void_upgrader_winning import VoidUpgraderWinning
from apps.api.app.models.void_upgrader_seed import VoidUpgraderSeed
from apps.api.app.models.void_upgrader_settings import VoidUpgraderSettings

# Tunables (v1 constants; move to config later if needed).
COINS_PER_VC = 1000       # 1 Void Coin == this many in-game coins (used only by the seeder)
RTP = 0.90                # return-to-player; house edge = 1 - RTP
MIN_STAKE = 1
MAX_MULTIPLIER = 100.0    # cap variance: reward may be at most 100x the stake
MAX_CHANCE = 0.90         # even a near-value upgrade keeps at least 10% risk
JACKPOT_ENABLED = True
JACKPOT_RATE = 0.01       # share of each paid stake that feeds the pot
JACKPOT_CHANCE = 0.001    # per-spin chance to scoop the whole pot
JACKPOT_SEED = 500        # pot floor after a scoop
DAILY_FREE_ENABLED = True
DAILY_FREE_STAKE = 25     # house-paid stake for the once-a-day free spin


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
                    "jackpot_enabled": JACKPOT_ENABLED, "jackpot_rate": JACKPOT_RATE,
                    "jackpot_chance": JACKPOT_CHANCE, "jackpot_seed": JACKPOT_SEED,
                    "daily_free_enabled": DAILY_FREE_ENABLED, "daily_free_stake": DAILY_FREE_STAKE,
                }
            else:
                self._settings_cache = {
                    "rtp": float(row.rtp), "coins_per_vc": int(row.coins_per_vc),
                    "min_stake": int(row.min_stake), "max_multiplier": float(row.max_multiplier),
                    "max_chance": float(row.max_chance),
                    "jackpot_enabled": bool(row.jackpot_enabled), "jackpot_rate": float(row.jackpot_rate),
                    "jackpot_chance": float(row.jackpot_chance), "jackpot_seed": int(row.jackpot_seed),
                    "daily_free_enabled": bool(row.daily_free_enabled), "daily_free_stake": int(row.daily_free_stake),
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
        free: bool = False,
    ) -> dict:
        reward = self._reward(reward_id)
        cfg = self.settings()
        balance = int(account.void_coins or 0)
        daily_streak: int | None = None

        if free:
            if not cfg["daily_free_enabled"]:
                raise VoidUpgraderError("Ежедневный бесплатный спин отключён.")
            # Battle Pass level boosts the free stake (higher pass ⇒ juicier daily spin).
            stake = self._scaled_free_stake(int(cfg["daily_free_stake"]), self._bp_level(account.minecraft_nickname))
            if stake >= int(reward.vc_value):
                raise VoidUpgraderError("Для бесплатного спина выбери награду дороже.")
            daily_streak = self._try_claim_daily(account)   # raises if already used today
        else:
            stake = int(stake)
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

        # Commit-reveal RNG: roll from the player's committed active seed + its running nonce.
        # The seed's SHA-256 is shown to the player before spinning; the raw seed is revealed
        # only on rotation, at which point every spin under it becomes verifiable.
        seed_row = self._active_seed_for_update(account)
        server_seed = seed_row.server_seed
        client_seed = (client_seed or secrets.token_hex(8))[:64]
        nonce = int(seed_row.nonce)
        digest = hmac.new(server_seed.encode(), f"{client_seed}:{nonce}".encode(), hashlib.sha256).hexdigest()
        roll = int(digest[:15], 16) / float(16 ** 15)   # uniform in [0, 1)
        won = roll < win_chance

        if free:
            # House pays the stake — no player balance change.
            new_balance = balance
        else:
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
        seed_row.nonce = nonce + 1   # advance the commit-reveal counter for this seed

        if won:
            # Item goes to the player's Upgrader inventory — they later CLAIM it in-game or SELL it for VC.
            self.session.add(VoidUpgraderWinning(
                server_id=self.server_id, user_id=account.user_id,
                minecraft_nickname=account.minecraft_nickname,
                item_key=reward.item_key, display_name=reward.display_name,
                vc_value=int(reward.vc_value), amount=int(reward.amount or 1),
                tier=reward.tier, give_command=reward.give_command,
            ))

        # Server-wide jackpot: only paid spins feed the pot and can scoop it.
        jackpot: dict | None = None
        if not free and cfg["jackpot_enabled"]:
            jackpot = self._process_jackpot(account, stake, server_seed, client_seed, nonce, cfg)
            if jackpot and jackpot.get("hit"):
                new_balance = jackpot["new_void_coins"]

        self.session.commit()

        return {
            "won": won,
            "roll": round(roll, 6),
            "win_chance": round(win_chance, 6),
            "multiplier": round(multiplier, 4),
            "stake": stake,
            "new_void_coins": new_balance,
            "free": free,
            "daily_streak": daily_streak,
            "jackpot": jackpot,
            "reward": {
                "id": str(reward.id),
                "item_key": reward.item_key,
                "display_name": reward.display_name,
                "image_url": reward.image_url,
                "vc_value": int(reward.vc_value),
                "amount": int(reward.amount or 1),
                "tier": reward.tier,
            },
            # Commit only — the raw active seed stays secret until the player rotates it.
            "server_seed_hash": hashlib.sha256(server_seed.encode()).hexdigest(),
            "client_seed": client_seed,
            "nonce": nonce,
        }

    # ── daily free spin ──────────────────────────────────────────────────────────
    def _try_claim_daily(self, account: PlayerAccount) -> int:
        """Atomically claim today's free spin; returns the new streak. Raises if already used today."""
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        stmt = (
            pg_insert(VoidUpgraderDaily)
            .values(
                server_id=self.server_id, user_id=account.user_id,
                minecraft_nickname=account.minecraft_nickname,
                last_free_spin_date=today, streak=1,
            )
            .on_conflict_do_update(
                constraint="uq_void_upgrader_daily_server_user",
                set_={
                    "last_free_spin_date": today,
                    "minecraft_nickname": account.minecraft_nickname,
                    "streak": case(
                        (VoidUpgraderDaily.last_free_spin_date == yesterday, VoidUpgraderDaily.streak + 1),
                        else_=1,
                    ),
                },
                where=VoidUpgraderDaily.last_free_spin_date < today,
            )
            .returning(VoidUpgraderDaily.streak)
        )
        res = self.session.execute(stmt).first()
        if res is None:
            self.session.rollback()
            raise VoidUpgraderError("Бесплатный спин уже использован сегодня. Возвращайся завтра!")
        return int(res[0])

    def _bp_level(self, nickname: str) -> int:
        """Current Battle Pass level for this player on this server (0 if none)."""
        lvl = self.session.execute(
            select(BattlePassProgress.level).where(
                BattlePassProgress.server_id == self.server_id,
                func.lower(BattlePassProgress.minecraft_nickname) == (nickname or "").lower(),
            )
        ).scalar_one_or_none()
        return int(lvl or 0)

    @staticmethod
    def _scaled_free_stake(base: int, bp_level: int) -> int:
        """Free daily stake grows with BP level: +2%/level, capped at 4×base."""
        factor = min(4.0, 1.0 + max(0, bp_level) / 50.0)
        return max(base, int(round(base * factor)))

    def daily_status(self, account: PlayerAccount) -> dict:
        cfg = self.settings()
        row = self.session.execute(
            select(VoidUpgraderDaily).where(
                VoidUpgraderDaily.server_id == self.server_id,
                VoidUpgraderDaily.user_id == account.user_id,
            )
        ).scalar_one_or_none()
        today = datetime.now(timezone.utc).date()
        available = cfg["daily_free_enabled"] and (row is None or row.last_free_spin_date < today)
        streak = int(row.streak) if row else 0
        if row and row.last_free_spin_date < today - timedelta(days=1):
            streak = 0   # streak already broken (a day was skipped)
        bp_level = self._bp_level(account.minecraft_nickname)
        return {
            "enabled": bool(cfg["daily_free_enabled"]),
            "available": bool(available),
            "free_stake": self._scaled_free_stake(int(cfg["daily_free_stake"]), bp_level),
            "streak": streak,
            "bp_level": bp_level,
        }

    # ── server-wide jackpot ──────────────────────────────────────────────────────
    def _process_jackpot(self, account, stake, server_seed, client_seed, nonce, cfg) -> dict:
        contribution = int(round(int(stake) * float(cfg["jackpot_rate"])))
        # Ensure the pot row exists (seed floor), then add this spin's contribution.
        self.session.execute(
            pg_insert(VoidUpgraderJackpot)
            .values(server_id=self.server_id, amount=int(cfg["jackpot_seed"]))
            .on_conflict_do_nothing(constraint="uq_void_upgrader_jackpot_server")
        )
        self.session.execute(
            update(VoidUpgraderJackpot)
            .where(VoidUpgraderJackpot.server_id == self.server_id)
            .values(amount=VoidUpgraderJackpot.amount + contribution)
        )
        # Independent scoop roll from a distinct HMAC label.
        j_digest = hmac.new(server_seed.encode(), f"jackpot:{client_seed}:{nonce}".encode(), hashlib.sha256).hexdigest()
        j_roll = int(j_digest[:15], 16) / float(16 ** 15)
        hit = j_roll < float(cfg["jackpot_chance"])

        if not hit:
            amount = int(self.session.execute(
                select(VoidUpgraderJackpot.amount).where(VoidUpgraderJackpot.server_id == self.server_id)
            ).scalar_one())
            return {"amount": amount, "hit": False}

        # Lock the pot row, pay out the whole pot, reset to seed.
        pot_row = self.session.execute(
            select(VoidUpgraderJackpot).where(VoidUpgraderJackpot.server_id == self.server_id).with_for_update()
        ).scalar_one()
        pot = int(pot_row.amount)
        pot_row.amount = int(cfg["jackpot_seed"])
        pot_row.last_winner_nickname = account.minecraft_nickname
        pot_row.last_amount = pot
        pot_row.last_won_at = func.now()
        bal = self.session.execute(
            update(PlayerAccount)
            .where(PlayerAccount.user_id == account.user_id)
            .values(void_coins=PlayerAccount.void_coins + pot)
            .returning(PlayerAccount.void_coins)
        ).first()
        new_balance = int(bal[0]) if bal else pot
        self.session.expire(account, ["void_coins"])
        return {"amount": int(cfg["jackpot_seed"]), "hit": True, "won_amount": pot, "new_void_coins": new_balance}

    def jackpot(self) -> dict:
        cfg = self.settings()
        row = self.session.execute(
            select(VoidUpgraderJackpot).where(VoidUpgraderJackpot.server_id == self.server_id)
        ).scalar_one_or_none()
        amount = int(row.amount) if row else int(cfg["jackpot_seed"])
        return {
            "enabled": bool(cfg["jackpot_enabled"]),
            "amount": amount,
            "last_winner": row.last_winner_nickname if row else None,
            "last_amount": int(row.last_amount) if (row and row.last_amount is not None) else None,
        }

    # ── weekly leaderboard ───────────────────────────────────────────────────────
    def weekly_leaderboard(self, limit: int = 10) -> dict:
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = self.session.execute(
            select(
                VoidUpgraderSpin.minecraft_nickname,
                func.max(VoidUpgraderSpin.reward_vc_value).label("biggest"),
                func.sum(VoidUpgraderSpin.reward_vc_value).label("total"),
                func.count(VoidUpgraderSpin.id).label("wins"),
            )
            .where(
                VoidUpgraderSpin.server_id == self.server_id,
                VoidUpgraderSpin.won.is_(True),
                VoidUpgraderSpin.created_at >= week_start,
            )
            .group_by(VoidUpgraderSpin.minecraft_nickname)
            .order_by(func.max(VoidUpgraderSpin.reward_vc_value).desc())
            .limit(limit)
        ).all()
        return {
            "week_start": week_start.isoformat(),
            "entries": [
                {"nickname": r[0], "biggest_win": int(r[1]), "total_won": int(r[2]), "wins": int(r[3])}
                for r in rows
            ],
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

    def sell_all(self, account: PlayerAccount) -> dict:
        rows = self.winnings(account.user_id)
        if not rows:
            return {"sold_count": 0, "vc_total": 0, "new_void_coins": int(account.void_coins or 0)}
        total = sum(int(w.vc_value) for w in rows)
        row = self.session.execute(
            update(PlayerAccount)
            .where(PlayerAccount.user_id == account.user_id)
            .values(void_coins=PlayerAccount.void_coins + total)
            .returning(PlayerAccount.void_coins)
        ).first()
        new_balance = int(row[0]) if row else total
        self.session.expire(account, ["void_coins"])
        for w in rows:
            self.session.delete(w)
        self.session.commit()
        return {"sold_count": len(rows), "vc_total": total, "new_void_coins": new_balance}

    def claim_all(self, account: PlayerAccount) -> dict:
        rows = self.winnings(account.user_id)
        for w in rows:
            self._enqueue_give(account.minecraft_nickname, w.item_key, int(w.amount or 1), w.display_name, w.give_command)
            self.session.delete(w)
        self.session.commit()
        return {"claimed_count": len(rows)}

    def stats(self, user_id: UUID) -> dict:
        row = self.session.execute(
            select(
                func.count(VoidUpgraderSpin.id),
                func.coalesce(func.sum(cast(VoidUpgraderSpin.won, Integer)), 0),
                func.coalesce(func.sum(VoidUpgraderSpin.stake), 0),
                func.coalesce(func.sum(VoidUpgraderSpin.reward_vc_value).filter(VoidUpgraderSpin.won.is_(True)), 0),
            ).where(
                VoidUpgraderSpin.server_id == self.server_id,
                VoidUpgraderSpin.user_id == user_id,
            )
        ).first()
        spins, wins, staked, won_value = (int(row[0]), int(row[1]), int(row[2]), int(row[3])) if row else (0, 0, 0, 0)
        return {
            "spins": spins,
            "wins": wins,
            "win_rate": round(wins / spins, 4) if spins else 0.0,
            "vc_staked": staked,
            "vc_won": won_value,
        }

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

    # ── commit-reveal fairness ───────────────────────────────────────────────────
    def _active_seed_for_update(self, account: PlayerAccount) -> VoidUpgraderSeed:
        """Row-locked active seed for this player, created on first use."""
        row = self.session.execute(
            select(VoidUpgraderSeed)
            .where(VoidUpgraderSeed.server_id == self.server_id, VoidUpgraderSeed.user_id == account.user_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            self.session.execute(
                pg_insert(VoidUpgraderSeed)
                .values(server_id=self.server_id, user_id=account.user_id, server_seed=secrets.token_hex(16), nonce=0)
                .on_conflict_do_nothing(constraint="uq_void_upgrader_seed_server_user")
            )
            row = self.session.execute(
                select(VoidUpgraderSeed)
                .where(VoidUpgraderSeed.server_id == self.server_id, VoidUpgraderSeed.user_id == account.user_id)
                .with_for_update()
            ).scalar_one()
        return row

    def _ensure_seed(self, account: PlayerAccount) -> VoidUpgraderSeed:
        row = self.session.execute(
            select(VoidUpgraderSeed).where(
                VoidUpgraderSeed.server_id == self.server_id, VoidUpgraderSeed.user_id == account.user_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = self._active_seed_for_update(account)
            self.session.commit()
        return row

    def active_seed_value(self, account: PlayerAccount) -> str | None:
        return self.session.execute(
            select(VoidUpgraderSeed.server_seed).where(
                VoidUpgraderSeed.server_id == self.server_id, VoidUpgraderSeed.user_id == account.user_id
            )
        ).scalar_one_or_none()

    def fairness(self, account: PlayerAccount) -> dict:
        row = self._ensure_seed(account)
        return {
            "commit_hash": hashlib.sha256(row.server_seed.encode()).hexdigest(),
            "nonce": int(row.nonce),
            "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
        }

    def rotate_seed(self, account: PlayerAccount) -> dict:
        """Reveal the current active seed and commit a fresh one — every past spin under the
        old seed is now independently verifiable."""
        row = self._active_seed_for_update(account)
        old_seed = row.server_seed
        old_nonce = int(row.nonce)
        new_seed = secrets.token_hex(16)
        row.server_seed = new_seed
        row.nonce = 0
        row.rotated_at = func.now()
        self.session.commit()
        return {
            "revealed_seed": old_seed,
            "revealed_hash": hashlib.sha256(old_seed.encode()).hexdigest(),
            "revealed_spins": old_nonce,
            "commit_hash": hashlib.sha256(new_seed.encode()).hexdigest(),
        }
