"""
CS2 Instant Alert — Game Model.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Game(UUIDMixin, TimestampMixin, Base):
    """
    Steam game definition.

    Each game has a unique Steam App ID and configurable monitoring parameters.
    Adding a new game is a configuration change, not a code change.
    """

    __tablename__ = "games"

    steam_app_id: Mapped[int] = mapped_column(
        Integer, unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Game-specific monitoring configuration
    # e.g. {"branches": ["public"], "patch_notes_url": "...", "news_app_id": 730}
    monitor_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ─── Relationships ───
    subscriptions = relationship(
        "Subscription", back_populates="game", lazy="noload"
    )
    updates = relationship("Update", back_populates="game", lazy="noload")
    build_history = relationship("BuildHistory", back_populates="game", lazy="noload")
    state = relationship(
        "SteamAppState",
        back_populates="game",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Game(id={self.id}, name={self.name}, app_id={self.steam_app_id})>"
