"""
CS2 Instant Alert — Application Constants.

Immutable values used throughout the application.
"""

from __future__ import annotations

from enum import StrEnum, unique

# ─── Steam App IDs ───

CS2_APP_ID: int = 730
"""Counter-Strike 2 Steam Application ID."""


# ─── Notification Constants ───

@unique
class ChannelType(StrEnum):
    """Supported notification channel types."""

    TELEGRAM = "telegram"
    PUSHOVER = "pushover"
    NTFY = "ntfy"
    DISCORD = "discord"
    WEBHOOK = "webhook"
    EMAIL = "email"
    TASKER = "tasker"
    MACRODROID = "macrodroid"
    HOMEASSISTANT = "homeassistant"


@unique
class NotificationStatus(StrEnum):
    """Notification delivery status."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    ACKNOWLEDGED = "acknowledged"


@unique
class AckSource(StrEnum):
    """Source of alert acknowledgement."""

    TELEGRAM_BUTTON = "telegram_button"
    PUSHOVER_CALLBACK = "pushover_callback"
    API = "api"
    WEBSOCKET = "websocket"


# ─── Retry Constants ───

RETRY_INTERVALS_SECONDS: list[int] = [30, 60, 120]
"""Escalating retry intervals: 30s → 1m → 2m (then repeat last)."""

MAX_RETRY_DURATION_SECONDS: int = 3600
"""Maximum retry duration: 1 hour."""


# ─── Steam Monitoring ───

STEAM_DEFAULT_BRANCH: str = "public"
"""Default Steam branch to monitor."""

PICS_POLL_TIMEOUT_SECONDS: float = 10.0
"""Timeout for PICS product info requests."""

STEAM_STORE_RATE_LIMIT_WINDOW: int = 300
"""Steam Store API rate limit window: 5 minutes."""

STEAM_STORE_MAX_REQUESTS: int = 180
"""Max requests to Steam Store API per window (conservative)."""

CROSS_VALIDATION_MIN_SOURCES: int = 2
"""Minimum number of agreeing sources before emitting update event."""


# ─── Telegram ───

TELEGRAM_MAX_MESSAGE_LENGTH: int = 4096
"""Maximum Telegram message length."""

TELEGRAM_MAX_MESSAGES_PER_SECOND: int = 30
"""Telegram Bot API global rate limit."""

TELEGRAM_MAX_MESSAGES_PER_CHAT_PER_MINUTE: int = 20
"""Telegram rate limit per individual chat."""


# ─── Race Mode ───

RACE_MODE_DEFAULT_INTERVAL: int = 2
"""Race Mode polling interval in seconds."""

RACE_MODE_DEFAULT_DURATION: int = 30
"""Race Mode duration in minutes."""


# ─── General ───

DEFAULT_TIMEZONE: str = "Europe/Moscow"
"""Default timezone for new users."""

DEFAULT_LANGUAGE: str = "ru"
"""Default language for new users."""

SUPPORTED_LANGUAGES: list[str] = ["ru", "en"]
"""Supported UI languages."""

PATCH_NOTES_POLL_INTERVAL_SECONDS: int = 30
"""Interval for polling patch notes after update detection."""

PATCH_NOTES_POLL_DURATION_SECONDS: int = 7200
"""Duration for patch notes polling: 2 hours."""
