"""
CS2 Instant Alert — Subscription Repository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.subscription import Subscription
from app.models.user import User
from app.repositories.base import BaseRepository


class SubscriptionRepository(BaseRepository[Subscription]):
    """Repository for Subscription entity with domain-specific queries."""

    model = Subscription

    async def get_by_user_and_game(
        self, user_id: uuid.UUID, game_id: uuid.UUID
    ) -> Subscription | None:
        """Find a subscription for a specific user-game pair."""
        stmt = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.game_id == game_id,
        )
        return await self._execute_scalar(stmt)

    async def get_user_subscriptions(
        self, user_id: uuid.UUID, active_only: bool = True
    ) -> list[Subscription]:
        """Get all subscriptions for a user."""
        stmt = select(Subscription).where(Subscription.user_id == user_id)
        if active_only:
            stmt = stmt.where(Subscription.is_active.is_(True))
        return await self._execute_query(stmt)

    async def get_game_subscribers(
        self, game_id: uuid.UUID, active_only: bool = True
    ) -> list[Subscription]:
        """Get all subscriptions for a game (to find subscribers)."""
        stmt = select(Subscription).where(Subscription.game_id == game_id)
        if active_only:
            stmt = stmt.where(Subscription.is_active.is_(True))
        return await self._execute_query(stmt)

    async def get_active_subscribers(
        self, game_id: uuid.UUID
    ) -> list[tuple[Subscription, User]]:
        """Get all active subscriptions and their associated users for a game."""
        stmt = (
            select(Subscription, User)
            .join(User, Subscription.user_id == User.id)
            .where(
                Subscription.game_id == game_id,
                Subscription.is_active.is_(True),
                User.is_active.is_(True)
            )
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def get_critical_subscribers(
        self, game_id: uuid.UUID
    ) -> list[Subscription]:
        """Get subscribers with critical notifications enabled for a game."""
        stmt = select(Subscription).where(
            Subscription.game_id == game_id,
            Subscription.is_active.is_(True),
            Subscription.critical_enabled.is_(True),
        )
        return await self._execute_query(stmt)

    async def subscribe(
        self,
        user_id: uuid.UUID,
        game_id: uuid.UUID,
        critical_enabled: bool = False,
    ) -> Subscription:
        """
        Subscribe a user to a game. Re-activates if previously unsubscribed.
        """
        existing = await self.get_by_user_and_game(user_id, game_id)
        if existing:
            if not existing.is_active:
                await self.update_by_id(existing.id, is_active=True)
                await self._session.refresh(existing)
            return existing

        sub = Subscription(
            user_id=user_id,
            game_id=game_id,
            critical_enabled=critical_enabled,
        )
        return await self.create(sub)

    async def unsubscribe(
        self, user_id: uuid.UUID, game_id: uuid.UUID
    ) -> bool:
        """Soft-unsubscribe a user from a game."""
        sub = await self.get_by_user_and_game(user_id, game_id)
        if sub and sub.is_active:
            await self.update_by_id(sub.id, is_active=False)
            return True
        return False
