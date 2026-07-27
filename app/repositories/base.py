"""
CS2 Instant Alert — Generic Async Repository.

Provides a type-safe, reusable base for all entity repositories.
Implements standard CRUD operations with SQLAlchemy 2.0 async style.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic async repository with standard CRUD operations.

    Subclasses specify the model class and can add domain-specific queries.
    """

    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelType | None:
        """Get a single entity by its UUID primary key."""
        return await self._session.get(self.model, entity_id)

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ModelType]:
        """Get all entities with pagination."""
        stmt = select(self.model).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count total entities."""
        stmt = select(func.count()).select_from(self.model)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def create(self, entity: ModelType) -> ModelType:
        """Add a new entity to the session."""
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def create_many(self, entities: list[ModelType]) -> list[ModelType]:
        """Add multiple entities to the session."""
        self._session.add_all(entities)
        await self._session.flush()
        for entity in entities:
            await self._session.refresh(entity)
        return entities

    async def update_by_id(
        self, entity_id: uuid.UUID, **values: Any
    ) -> ModelType | None:
        """Update an entity by ID with the given values."""
        stmt = (
            update(self.model)
            .where(self.model.id == entity_id)  # type: ignore[attr-defined]
            .values(**values)
            .returning(self.model)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one_or_none()

    async def update(self, entity: ModelType, **values: Any) -> ModelType:
        """Update an attached entity and refresh its database state."""
        for field, value in values.items():
            setattr(entity, field, value)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete_by_id(self, entity_id: uuid.UUID) -> bool:
        """Delete an entity by ID. Returns True if deleted."""
        stmt = delete(self.model).where(
            self.model.id == entity_id  # type: ignore[attr-defined]
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def exists(self, entity_id: uuid.UUID) -> bool:
        """Check if an entity exists by ID."""
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.id == entity_id)  # type: ignore[attr-defined]
        )
        result = await self._session.execute(stmt)
        return result.scalar_one() > 0

    async def _execute_query(self, stmt: Select) -> list[ModelType]:
        """Execute a SELECT and return list of model instances."""
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _execute_scalar(self, stmt: Select) -> ModelType | None:
        """Execute a SELECT and return a single model instance or None."""
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
