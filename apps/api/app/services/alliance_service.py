from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models.alliance import (
    Alliance,
    AllianceMember,
    AllianceMemberRole,
    AllianceProposal,
    AllianceProposalStatus,
    AllianceProposalType,
    AllianceVote,
    AllianceVoteChoice,
)
from apps.api.app.models.nation import Nation
from apps.api.app.models.nation_member import NationMember
from apps.api.app.models.nation_stat import NationStat
from apps.api.app.models.nation_treasury_transaction import NationTreasuryTransaction
from apps.api.app.models.user import User
from apps.api.app.services.nation_activity_service import NationActivityService

MIN_ALLIANCE_POWER_TO_CREATE = 50000
DEFAULT_TRANSFER_FEE_PERCENT = Decimal("5.00")
MONEY_QUANT = Decimal("0.01")


class AllianceValidationError(Exception):
    pass


class AlliancePermissionError(Exception):
    pass


class AllianceNotFoundError(Exception):
    pass


class AllianceService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id
        self.activity = NationActivityService(session, server_id)

    def list_alliances(self) -> list[Alliance]:
        return self.session.execute(
            select(Alliance)
            .options(joinedload(Alliance.members))
            .order_by(Alliance.created_at.desc())
        ).unique().scalars().all()

    def get_by_slug(self, slug: str) -> Alliance:
        alliance = self.session.execute(
            select(Alliance)
            .options(joinedload(Alliance.members))
            .where(Alliance.slug == slug, Alliance.server_id == self.server_id)
        ).unique().scalar_one_or_none()
        if alliance is None:
            raise AllianceNotFoundError("Альянс не найден.")
        return alliance

    def get_nation_alliance(self, nation_id: UUID) -> Alliance | None:
        member = self.session.execute(
            select(AllianceMember).where(AllianceMember.nation_id == nation_id)
        ).scalar_one_or_none()
        if member is None:
            return None
        return self.session.get(Alliance, member.alliance_id)

    def create_alliance(self, *, current_user: User, source_nation: Nation, slug: str, title: str, tag: str, alliance_type: str, description: str | None = None) -> Alliance:
        self._require_nation_manage_permission(current_user, source_nation.id)
        self._assert_nation_can_create_alliance(source_nation.id)

        slug = (slug or "").strip().lower()
        title = (title or "").strip()
        tag = (tag or "").strip().upper()
        description = (description or "").strip() or None

        existing = self.session.execute(
            select(Alliance).where(Alliance.slug == slug, Alliance.server_id == self.server_id)
        ).scalar_one_or_none()
        if existing is not None:
            raise AllianceValidationError("Такой slug альянса уже занят.")

        alliance = Alliance(
            server_id=self.server_id,
            slug=slug,
            title=title,
            tag=tag,
            alliance_type=alliance_type,
            description=description,
            founder_nation_id=source_nation.id,
            min_power_required=MIN_ALLIANCE_POWER_TO_CREATE,
            transfer_fee_percent=DEFAULT_TRANSFER_FEE_PERCENT,
            allow_internal_transfers=True,
            allow_joint_defense=True,
            allow_trade_bonus=False,
            allow_pvp_protection=False,
            policy_flags_json={},
        )
        self.session.add(alliance)
        self.session.flush()

        self.session.add(AllianceMember(server_id=self.server_id, alliance_id=alliance.id, nation_id=source_nation.id, role=AllianceMemberRole.founder.value))

        self.activity.record(
            nation_id=source_nation.id,
            event_type="alliance_created",
            actor_user_id=current_user.id,
            message=f"Государство создало альянс {title}.",
            metadata={"alliance_slug": slug, "alliance_type": alliance_type},
        )

        self.session.commit()
        self.session.refresh(alliance)
        return alliance

    def join_alliance(self, *, current_user: User, source_nation: Nation, alliance_slug: str) -> Alliance:
        self._require_nation_manage_permission(current_user, source_nation.id)
        self._assert_nation_can_join_alliance(source_nation.id)

        alliance = self.get_by_slug(alliance_slug)
        self.session.add(AllianceMember(server_id=self.server_id, alliance_id=alliance.id, nation_id=source_nation.id, role=AllianceMemberRole.member.value))

        self.activity.record(
            nation_id=source_nation.id,
            event_type="alliance_joined",
            actor_user_id=current_user.id,
            message=f"Государство вступило в альянс {alliance.title}.",
            metadata={"alliance_slug": alliance.slug},
        )

        self.session.commit()
        self.session.refresh(alliance)
        return alliance

    def leave_alliance(self, *, current_user: User, source_nation: Nation) -> dict[str, Any]:
        self._require_nation_manage_permission(current_user, source_nation.id)

        member = self.session.execute(select(AllianceMember).where(AllianceMember.nation_id == source_nation.id)).scalar_one_or_none()
        if member is None:
            raise AllianceValidationError("Государство не состоит в альянсе.")

        alliance = self.session.execute(
            select(Alliance).options(joinedload(Alliance.members)).where(Alliance.id == member.alliance_id)
        ).unique().scalar_one_or_none()
        if alliance is None:
            raise AllianceNotFoundError("Альянс не найден.")

        other_members = [item for item in alliance.members if item.nation_id != source_nation.id]

        # If only 2 or fewer nations are in the alliance, leaving always dissolves it
        if len(alliance.members) <= 2:
            slug = alliance.slug
            title = alliance.title
            self.activity.record(
                nation_id=source_nation.id,
                event_type="alliance_dissolved",
                actor_user_id=current_user.id,
                message=f"Альянс {title} распущен после выхода последнего участника.",
                metadata={"alliance_slug": slug},
            )
            for m in list(alliance.members):
                self.session.delete(m)
            self.session.delete(alliance)
            self.session.commit()
            return {"message": "Альянс распущен.", "alliance_slug": slug, "dissolved": True}

        is_founder = member.role == AllianceMemberRole.founder.value or alliance.founder_nation_id == source_nation.id

        if is_founder:
            raise AllianceValidationError("Государство-основатель не может выйти, пока в альянсе есть другие участники.")

        self._cleanup_nation_alliance_participation(alliance.id, source_nation.id, "nation left alliance")
        self.session.delete(member)

        self.activity.record(
            nation_id=source_nation.id,
            event_type="alliance_left",
            actor_user_id=current_user.id,
            message=f"Государство вышло из альянса {alliance.title}.",
            metadata={"alliance_slug": alliance.slug},
        )

        self.session.commit()
        return {"message": "Государство вышло из альянса.", "alliance_slug": alliance.slug, "dissolved": False}

    def update_policies(self, *, current_user: User, source_nation: Nation, alliance_slug: str, data: dict[str, Any]) -> Alliance:
        self._require_founder_permission(current_user, source_nation.id, alliance_slug)
        alliance = self.get_by_slug(alliance_slug)
        self._apply_policy_patch(alliance, data)
        self.activity.record(
            nation_id=source_nation.id,
            event_type="alliance_policy_updated",
            actor_user_id=current_user.id,
            message=f"Обновлены политики альянса {alliance.title}.",
            metadata={"alliance_slug": alliance.slug, "fields": sorted(list(data.keys()))},
        )
        self.session.commit()
        self.session.refresh(alliance)
        return alliance

    def create_proposal(self, *, current_user: User, source_nation: Nation, alliance_slug: str, proposal_type: str, title: str, description: str | None, payload_json: dict[str, Any]) -> AllianceProposal:
        self._require_member_permission(current_user, source_nation.id, alliance_slug)
        alliance = self.get_by_slug(alliance_slug)
        normalized_type = str(proposal_type or "").strip().lower()
        if normalized_type not in {item.value for item in AllianceProposalType}:
            raise AllianceValidationError("Неизвестный тип предложения альянса.")
        proposal = AllianceProposal(
            server_id=self.server_id,
            alliance_id=alliance.id,
            proposer_nation_id=source_nation.id,
            proposal_type=normalized_type,
            status=AllianceProposalStatus.open.value,
            title=(title or "").strip(),
            description=((description or "").strip() or None),
            payload_json=payload_json or {},
            execution_status="pending",
        )
        self.session.add(proposal)
        self.session.flush()
        self.activity.record(
            nation_id=source_nation.id,
            event_type="alliance_proposal_created",
            actor_user_id=current_user.id,
            message=f"Создано предложение альянса: {proposal.title}.",
            metadata={"alliance_slug": alliance.slug, "proposal_type": normalized_type},
        )
        self.session.commit()
        self.session.refresh(proposal)
        return proposal

    def vote_on_proposal(self, *, current_user: User, source_nation: Nation, proposal_id: UUID, vote: str, comment: str | None = None) -> AllianceProposal:
        proposal = self.session.execute(
            select(AllianceProposal).options(joinedload(AllianceProposal.votes)).where(AllianceProposal.id == proposal_id)
        ).unique().scalar_one_or_none()
        if proposal is None:
            raise AllianceNotFoundError("Предложение не найдено.")

        alliance = self.session.get(Alliance, proposal.alliance_id)
        if alliance is None:
            raise AllianceNotFoundError("Альянс не найден.")

        self._require_member_permission(current_user, source_nation.id, alliance.slug)

        if proposal.status != AllianceProposalStatus.open.value:
            raise AllianceValidationError("Голосование по этому предложению уже закрыто.")

        normalized_vote = str(vote or "").strip().lower()
        if normalized_vote not in {item.value for item in AllianceVoteChoice}:
            raise AllianceValidationError("Недопустимый вариант голоса.")

        existing = self.session.execute(
            select(AllianceVote).where(AllianceVote.proposal_id == proposal.id, AllianceVote.nation_id == source_nation.id)
        ).scalar_one_or_none()

        if existing is None:
            existing = AllianceVote(server_id=self.server_id, proposal_id=proposal.id, nation_id=source_nation.id, vote=normalized_vote, comment=comment)
            self.session.add(existing)
        else:
            existing.vote = normalized_vote
            existing.comment = comment

        self.session.flush()
        self.session.refresh(proposal)
        self._recalculate_proposal_status(proposal)

        if proposal.status == AllianceProposalStatus.approved.value:
            self._execute_approved_proposal(proposal, alliance, current_user)

        if proposal.status == AllianceProposalStatus.rejected.value and proposal.execution_status == "pending":
            proposal.execution_status = "skipped"
            proposal.execution_result = "Proposal was rejected by voting."
            proposal.executed_at = None

        self.activity.record(
            nation_id=source_nation.id,
            event_type="alliance_vote_cast",
            actor_user_id=current_user.id,
            message=f"Подан голос по предложению альянса: {proposal.title}.",
            metadata={"proposal_id": str(proposal.id), "vote": normalized_vote},
        )

        self.session.commit()
        self.session.refresh(proposal)
        return proposal

    def list_proposals(self, alliance_slug: str) -> list[AllianceProposal]:
        alliance = self.get_by_slug(alliance_slug)
        return self.session.execute(
            select(AllianceProposal)
            .options(joinedload(AllianceProposal.votes))
            .where(AllianceProposal.alliance_id == alliance.id)
            .order_by(AllianceProposal.created_at.desc())
        ).unique().scalars().all()

    def transfer_between_members(self, *, current_user: User, source_nation: Nation, alliance_slug: str, from_nation_slug: str, to_nation_slug: str, amount: Decimal, comment: str | None = None) -> dict[str, str]:
        self._require_member_permission(current_user, source_nation.id, alliance_slug)
        alliance = self.get_by_slug(alliance_slug)
        from_nation = self._get_nation_by_slug(from_nation_slug)
        to_nation = self._get_nation_by_slug(to_nation_slug)

        if from_nation.id != source_nation.id:
            raise AlliancePermissionError("Можно переводить средства только из казны своего государства.")

        result = self._perform_alliance_transfer(
            alliance=alliance,
            from_nation=from_nation,
            to_nation=to_nation,
            amount=amount,
            created_by_user_id=current_user.id,
            comment=comment,
            activity_message="Из казны государства выполнен перевод в союзное государство.",
        )
        self.session.commit()
        return result

    def list_transactions(self, alliance_slug: str, limit: int = 25) -> list[NationTreasuryTransaction]:
        alliance = self.get_by_slug(alliance_slug)
        return self.session.execute(
            select(NationTreasuryTransaction)
            .where(NationTreasuryTransaction.alliance_id == alliance.id)
            .order_by(NationTreasuryTransaction.created_at.desc())
            .limit(limit)
        ).scalars().all()

    def calculate_transfer_fee(self, amount: Decimal, percent: Decimal) -> Decimal:
        return ((amount * percent) / Decimal("100")).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    def _execute_approved_proposal(self, proposal: AllianceProposal, alliance: Alliance, current_user: User) -> None:
        if proposal.execution_status == "executed":
            return
        try:
            result = self._execute_proposal(proposal, alliance, current_user)
            proposal.status = AllianceProposalStatus.executed.value
            proposal.execution_status = "executed"
            proposal.execution_result = (result or "Proposal executed.")[:500]
            proposal.executed_at = datetime.now(timezone.utc)
        except Exception as exc:
            proposal.execution_status = "failed"
            proposal.execution_result = str(exc)[:500]
            proposal.executed_at = None

    def _execute_proposal(self, proposal: AllianceProposal, alliance: Alliance, current_user: User) -> str:
        payload = proposal.payload_json or {}

        if proposal.proposal_type == AllianceProposalType.set_policy.value:
            self._apply_policy_patch(alliance, payload)
            self.activity.record(
                nation_id=proposal.proposer_nation_id,
                actor_user_id=current_user.id,
                event_type="alliance_policy_updated_by_proposal",
                message=f"Политики альянса {alliance.title} изменены по голосованию.",
                metadata={"alliance_slug": alliance.slug, "proposal_id": str(proposal.id)},
            )
            return "Политики альянса обновлены."

        if proposal.proposal_type == AllianceProposalType.treasury_transfer.value:
            from_nation = self._get_nation_by_slug(str(payload.get("from_nation_slug", "")).strip())
            to_nation = self._get_nation_by_slug(str(payload.get("to_nation_slug", "")).strip())
            amount = Decimal(str(payload.get("amount", "0")))
            comment = payload.get("comment")
            result = self._perform_alliance_transfer(
                alliance=alliance,
                from_nation=from_nation,
                to_nation=to_nation,
                amount=amount,
                created_by_user_id=current_user.id,
                comment=comment,
                activity_message="Перевод внутри альянса выполнен по одобренному предложению.",
            )
            return result["message"]

        if proposal.proposal_type == AllianceProposalType.add_member.value:
            target_nation = self._get_nation_by_slug(str(payload.get("nation_slug", "")).strip())
            self._assert_nation_can_join_alliance(target_nation.id)
            self.session.add(AllianceMember(server_id=self.server_id, alliance_id=alliance.id, nation_id=target_nation.id, role=AllianceMemberRole.member.value))
            self.activity.record(
                nation_id=target_nation.id,
                actor_user_id=current_user.id,
                event_type="alliance_joined_by_proposal",
                message=f"Государство вступило в альянс {alliance.title} по решению голосования.",
                metadata={"alliance_slug": alliance.slug, "proposal_id": str(proposal.id)},
            )
            return f"Государство {target_nation.title} добавлено в альянс."

        if proposal.proposal_type == AllianceProposalType.remove_member.value:
            target_nation = self._get_nation_by_slug(str(payload.get("nation_slug", "")).strip())
            member = self.session.execute(
                select(AllianceMember).where(AllianceMember.alliance_id == alliance.id, AllianceMember.nation_id == target_nation.id)
            ).scalar_one_or_none()
            if member is None:
                raise AllianceValidationError("Указанное государство не состоит в этом альянсе.")
            if member.role == AllianceMemberRole.founder.value or target_nation.id == alliance.founder_nation_id:
                raise AllianceValidationError("Государство-основатель нельзя удалить из альянса этим способом.")
            self._cleanup_nation_alliance_participation(alliance.id, target_nation.id, "nation removed from alliance")
            self.session.delete(member)
            self.activity.record(
                nation_id=target_nation.id,
                actor_user_id=current_user.id,
                event_type="alliance_removed_by_proposal",
                message=f"Государство исключено из альянса {alliance.title} по решению голосования.",
                metadata={"alliance_slug": alliance.slug, "proposal_id": str(proposal.id)},
            )
            return f"Государство {target_nation.title} исключено из альянса."

        raise AllianceValidationError("Неподдерживаемый тип proposal для исполнения.")

    def _perform_alliance_transfer(self, *, alliance: Alliance, from_nation: Nation, to_nation: Nation, amount: Decimal, created_by_user_id: UUID | None, comment: str | None, activity_message: str) -> dict[str, str]:
        if not alliance.allow_internal_transfers:
            raise AllianceValidationError("Внутренние переводы в этом альянсе отключены.")
        if amount <= 0:
            raise AllianceValidationError("Сумма перевода должна быть больше нуля.")
        self._assert_alliance_member(alliance.id, from_nation.id)
        self._assert_alliance_member(alliance.id, to_nation.id)
        if from_nation.id == to_nation.id:
            raise AllianceValidationError("Нельзя переводить средства в то же самое государство.")

        from_stat = self._get_or_create_nation_stat(from_nation.id)
        to_stat = self._get_or_create_nation_stat(to_nation.id)
        current_balance = Decimal(str(from_stat.treasury_balance or 0))
        if current_balance < amount:
            raise AllianceValidationError("Недостаточно средств в казне государства для перевода.")

        fee = self.calculate_transfer_fee(amount, Decimal(str(alliance.transfer_fee_percent or 0)))
        net_amount = (amount - fee).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

        from_stat.treasury_balance = (current_balance - amount).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        to_stat.treasury_balance = (Decimal(str(to_stat.treasury_balance or 0)) + net_amount).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        alliance.treasury_balance = (Decimal(str(alliance.treasury_balance or 0)) + fee).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

        metadata = {"alliance_slug": alliance.slug, "from_nation_slug": from_nation.slug, "to_nation_slug": to_nation.slug}

        self.session.add(NationTreasuryTransaction(
            server_id=self.server_id,
            transaction_type="alliance_transfer_out",
            nation_id=from_nation.id,
            counterparty_nation_id=to_nation.id,
            alliance_id=alliance.id,
            created_by_user_id=created_by_user_id,
            gross_amount=amount,
            fee_amount=fee,
            net_amount=net_amount,
            comment=comment,
            metadata_json=metadata,
        ))
        self.session.add(NationTreasuryTransaction(
            server_id=self.server_id,
            transaction_type="alliance_transfer_in",
            nation_id=to_nation.id,
            counterparty_nation_id=from_nation.id,
            alliance_id=alliance.id,
            created_by_user_id=created_by_user_id,
            gross_amount=amount,
            fee_amount=fee,
            net_amount=net_amount,
            comment=comment,
            metadata_json=metadata,
        ))
        self.session.add(NationTreasuryTransaction(
            server_id=self.server_id,
            transaction_type="alliance_fee_income",
            nation_id=None,
            counterparty_nation_id=None,
            alliance_id=alliance.id,
            created_by_user_id=created_by_user_id,
            gross_amount=fee,
            fee_amount=Decimal("0.00"),
            net_amount=fee,
            comment=comment,
            metadata_json=metadata,
        ))

        self.activity.record(
            nation_id=from_nation.id,
            actor_user_id=created_by_user_id,
            event_type="alliance_transfer_sent",
            message=activity_message,
            metadata={"alliance_slug": alliance.slug, "to_nation_slug": to_nation.slug, "amount": str(amount)},
        )
        self.activity.record(
            nation_id=to_nation.id,
            actor_user_id=created_by_user_id,
            event_type="alliance_transfer_received",
            message="Государство получило перевод от союзника.",
            metadata={"alliance_slug": alliance.slug, "from_nation_slug": from_nation.slug, "amount": str(net_amount)},
        )

        return {"message": f"Перевод выполнен: {from_nation.slug} -> {to_nation.slug}. К получению: {net_amount}, комиссия: {fee}."}

    def _cleanup_nation_alliance_participation(self, alliance_id: UUID, nation_id: UUID, reason: str) -> None:
        proposals = self.session.execute(
            select(AllianceProposal).options(joinedload(AllianceProposal.votes)).where(AllianceProposal.alliance_id == alliance_id)
        ).unique().scalars().all()

        for proposal in proposals:
            if proposal.proposer_nation_id == nation_id and proposal.status == AllianceProposalStatus.open.value:
                proposal.status = AllianceProposalStatus.expired.value
                proposal.execution_status = "skipped"
                proposal.execution_result = reason[:500]
                proposal.executed_at = None

            removable_votes = [vote for vote in list(proposal.votes or []) if vote.nation_id == nation_id]
            for vote in removable_votes:
                try:
                    proposal.votes.remove(vote)
                except ValueError:
                    pass
                self.session.delete(vote)

            if proposal.status == AllianceProposalStatus.open.value:
                self._recalculate_proposal_status(proposal)

    def _recalculate_proposal_status(self, proposal: AllianceProposal) -> None:
        votes = list(proposal.votes or [])
        if any(v.vote == AllianceVoteChoice.veto.value for v in votes):
            proposal.status = AllianceProposalStatus.rejected.value
            return
        yes_count = sum(1 for v in votes if v.vote == AllianceVoteChoice.yes.value)
        no_count = sum(1 for v in votes if v.vote == AllianceVoteChoice.no.value)
        if yes_count > no_count and yes_count > 0:
            proposal.status = AllianceProposalStatus.approved.value
        elif no_count >= yes_count and no_count > 0:
            proposal.status = AllianceProposalStatus.rejected.value
        else:
            proposal.status = AllianceProposalStatus.open.value

    def _apply_policy_patch(self, alliance: Alliance, data: dict[str, Any]) -> None:
        for field in ("transfer_fee_percent", "allow_internal_transfers", "allow_joint_defense", "allow_trade_bonus", "allow_pvp_protection", "policy_flags_json"):
            if field in data and data[field] is not None:
                setattr(alliance, field, data[field])

    def _require_nation_manage_permission(self, current_user: User, nation_id: UUID) -> None:
        membership = self.session.execute(
            select(NationMember).where(NationMember.nation_id == nation_id, NationMember.user_id == current_user.id)
        ).scalar_one_or_none()
        if membership is None or membership.role not in {"leader", "officer"}:
            raise AlliancePermissionError("Недостаточно прав для управления альянсом от имени этого государства.")

    def _require_founder_permission(self, current_user: User, nation_id: UUID, alliance_slug: str) -> None:
        self._require_nation_manage_permission(current_user, nation_id)
        alliance = self.get_by_slug(alliance_slug)
        member = self.session.execute(
            select(AllianceMember).where(AllianceMember.alliance_id == alliance.id, AllianceMember.nation_id == nation_id)
        ).scalar_one_or_none()
        if member is None or member.role != AllianceMemberRole.founder.value:
            raise AlliancePermissionError("Только государство-основатель может менять политики альянса.")

    def _require_member_permission(self, current_user: User, nation_id: UUID, alliance_slug: str) -> None:
        self._require_nation_manage_permission(current_user, nation_id)
        alliance = self.get_by_slug(alliance_slug)
        self._assert_alliance_member(alliance.id, nation_id)

    def _assert_alliance_member(self, alliance_id: UUID, nation_id: UUID) -> None:
        member = self.session.execute(
            select(AllianceMember).where(AllianceMember.alliance_id == alliance_id, AllianceMember.nation_id == nation_id)
        ).scalar_one_or_none()
        if member is None:
            raise AlliancePermissionError("Государство не состоит в этом альянсе.")

    def _assert_nation_can_create_alliance(self, nation_id: UUID) -> None:
        existing = self.session.execute(select(AllianceMember).where(AllianceMember.nation_id == nation_id)).scalar_one_or_none()
        if existing is not None:
            raise AllianceValidationError("Государство уже состоит в альянсе.")
        stat = self.session.execute(select(NationStat).where(NationStat.nation_id == nation_id)).scalar_one_or_none()
        prestige = int(getattr(stat, "prestige_score", 0) or 0)
        territory = int(getattr(stat, "territory_points", 0) or 0)
        total_power = prestige + territory
        if total_power < MIN_ALLIANCE_POWER_TO_CREATE:
            raise AllianceValidationError("Недостаточно силы государства для создания альянса.")

    def _assert_nation_can_join_alliance(self, nation_id: UUID) -> None:
        existing = self.session.execute(select(AllianceMember).where(AllianceMember.nation_id == nation_id)).scalar_one_or_none()
        if existing is not None:
            raise AllianceValidationError("Государство уже состоит в альянсе.")

    def _get_nation_by_slug(self, slug: str) -> Nation:
        nation = self.session.execute(select(Nation).where(Nation.slug == slug)).scalar_one_or_none()
        if nation is None:
            raise AllianceValidationError("Государство не найдено.")
        return nation

    def _get_or_create_nation_stat(self, nation_id: UUID) -> NationStat:
        stat = self.session.execute(select(NationStat).where(NationStat.nation_id == nation_id)).scalar_one_or_none()
        if stat is None:
            stat = NationStat(server_id=self.server_id, nation_id=nation_id)
            self.session.add(stat)
            self.session.flush()
        return stat
