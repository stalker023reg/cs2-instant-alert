"""
CS2 Instant Alert — User Repository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User entity with domain-specific queries."""

    model = User

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Find a user by their Telegram ID."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        return await self._execute_scalar(stmt)

    async def get_active_users(self) -> list[User]:
        """Get all active users."""
        stmt = select(User).where(User.is_active.is_(True))
        return await self._execute_query(stmt)

    async def get_admins(self) -> list[User]:
        """Get all admin users."""
        stmt = select(User).where(User.is_admin.is_(True), User.is_active.is_(True))
        return await self._execute_query(stmt)

    async def get_or_create_by_telegram(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> tuple[User, bool]:
        """
        Get existing user or create a new one.

        Returns:
            Tuple of (user, created) where created is True if user was just created.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            return user, False

        new_user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        created_user = await self.create(new_user)
        return created_user, True

    async def set_admin(self, user_id: uuid.UUID, is_admin: bool = True) -> User | None:
        """Toggle admin status for a user."""
        return await self.update_by_id(user_id, is_admin=is_admin)

    async def deactivate(self, user_id: uuid.UUID) -> User | None:
        """Deactivate a user."""
        return await self.update_by_id(user_id, is_active=False)
