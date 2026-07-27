"""
CS2 Instant Alert — FastAPI Dependencies.

Provides dependency injection for request-scoped resources:
database sessions, repositories, services.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppSettings, get_settings
from app.database.session import DatabaseSessionManager

# Module-level reference, set during app startup
_db_manager: DatabaseSessionManager | None = None


def set_db_manager(manager: DatabaseSessionManager) -> None:
    """Set the database manager instance (called during app startup)."""
    global _db_manager
    _db_manager = manager


def get_db_manager() -> DatabaseSessionManager:
    """Get the database manager instance."""
    if _db_manager is None:
        raise RuntimeError("Database manager not initialized")
    return _db_manager


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: provides a request-scoped async database session.

    Commits on success, rolls back on exception.
    """
    manager = get_db_manager()
    async with manager.session() as session:
        yield session


async def get_readonly_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: provides a read-only session (no commit).
    """
    manager = get_db_manager()
    async with manager.readonly_session() as session:
        yield session


def get_config() -> AppSettings:
    """FastAPI dependency: provides application settings."""
    return get_settings()
