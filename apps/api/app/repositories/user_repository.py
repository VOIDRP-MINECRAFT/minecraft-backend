from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_id_with_player_account(self, user_id: UUID) -> User | None:
        statement = (
            select(User)
            .options(joinedload(User.player_account))
            .where(User.id == user_id)
        )
        return self.session.execute(statement).unique().scalar_one_or_none()

    def get_by_login_or_email_normalized(self, login_or_email_normalized: str) -> User | None:
        statement = select(User).where(
            or_(
                User.site_login_normalized == login_or_email_normalized,
                User.email_normalized == login_or_email_normalized,
            )
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_by_login_or_email_normalized_with_player_account(
        self,
        login_or_email_normalized: str,
    ) -> User | None:
        statement = (
            select(User)
            .options(joinedload(User.player_account))
            .where(
                or_(
                    User.site_login_normalized == login_or_email_normalized,
                    User.email_normalized == login_or_email_normalized,
                )
            )
        )
        return self.session.execute(statement).unique().scalar_one_or_none()

    def get_by_site_login_normalized(self, site_login_normalized: str) -> User | None:
        statement = select(User).where(User.site_login_normalized == site_login_normalized)
        return self.session.execute(statement).scalar_one_or_none()

    def get_by_email_normalized(self, email_normalized: str) -> User | None:
        statement = select(User).where(User.email_normalized == email_normalized)
        return self.session.execute(statement).scalar_one_or_none()

    def add(self, user: User) -> User:
        self.session.add(user)
        return user
