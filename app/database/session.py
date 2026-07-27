"""
CS2 Instant Alert — Async Database Session Factory.

Provides async SQLAlchemy engine and session management
with proper connection pooling for PostgreSQL via asyncpg.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import AppSettings


class DatabaseSessionManager:
    """
    Manages async SQLAlchemy engine and session factory lifecycle.

    Usage:
        manager = DatabaseSessionManager(settings)
        await manager.initialize()

        async with manager.session() as session:
            ...

        await manager.close()
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def initialize(self) -> None:
        """Create the async engine and session factory."""
        self._engine = create_async_engine(
            self._settings.database_url,
            echo=self._settings.database_echo,
            pool_size=self._settings.database_pool_size,
            max_overflow=self._settings.database_max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def close(self) -> None:
        """Dispose the engine and release all connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("DatabaseSessionManager is not initialized. Call initialize() first.")
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Provide a transactional async session scope.

        Commits on success, rolls back on exception.
        """
        if self._session_factory is None:
            raise RuntimeError("DatabaseSessionManager is not initialized. Call initialize() first.")

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def readonly_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Provide a read-only async session scope (no commit).
        """
        if self._session_factory is None:
            raise RuntimeError("DatabaseSessionManager is not initialized. Call initialize() first.")

        session = self._session_factory()
        try:
            yield session
        finally:
            await session.close()
