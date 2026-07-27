"""
CS2 Instant Alert — Custom Exception Hierarchy.

All application-specific exceptions inherit from AppError.
This enables uniform error handling across layers.
"""

from __future__ import annotations


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str = "", *, code: str = "INTERNAL_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(self.message)


# ─── Configuration ───


class ConfigurationError(AppError):
    """Raised when application configuration is invalid or missing."""

    def __init__(self, message: str = "Invalid configuration") -> None:
        super().__init__(message, code="CONFIGURATION_ERROR")


# ─── Database ───


class DatabaseError(AppError):
    """Base exception for database-related errors."""

    def __init__(self, message: str = "Database error") -> None:
        super().__init__(message, code="DATABASE_ERROR")


class EntityNotFoundError(DatabaseError):
    """Raised when a requested entity does not exist."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} with id '{entity_id}' not found")
        self.code = "ENTITY_NOT_FOUND"


class DuplicateEntityError(DatabaseError):
    """Raised when attempting to create a duplicate entity."""

    def __init__(self, entity_type: str, field: str, value: str) -> None:
        self.entity_type = entity_type
        self.field = field
        self.value = value
        super().__init__(f"{entity_type} with {field}='{value}' already exists")
        self.code = "DUPLICATE_ENTITY"


# ─── Steam ───


class SteamError(AppError):
    """Base exception for Steam-related errors."""

    def __init__(self, message: str = "Steam error") -> None:
        super().__init__(message, code="STEAM_ERROR")


class SteamConnectionError(SteamError):
    """Raised when connection to Steam services fails."""

    def __init__(self, message: str = "Failed to connect to Steam") -> None:
        super().__init__(message)
        self.code = "STEAM_CONNECTION_ERROR"


class SteamRateLimitError(SteamError):
    """Raised when Steam API rate limit is hit."""

    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        msg = "Steam API rate limit exceeded"
        if retry_after:
            msg += f", retry after {retry_after}s"
        super().__init__(msg)
        self.code = "STEAM_RATE_LIMIT"


class SteamDataError(SteamError):
    """Raised when Steam returns unexpected or malformed data."""

    def __init__(self, message: str = "Unexpected Steam data format") -> None:
        super().__init__(message)
        self.code = "STEAM_DATA_ERROR"


# ─── Notifications ───


class NotificationError(AppError):
    """Base exception for notification-related errors."""

    def __init__(self, message: str = "Notification error") -> None:
        super().__init__(message, code="NOTIFICATION_ERROR")


class ChannelSendError(NotificationError):
    """Raised when a notification channel fails to deliver."""

    def __init__(self, channel_type: str, message: str = "") -> None:
        self.channel_type = channel_type
        full_msg = f"Failed to send via {channel_type}"
        if message:
            full_msg += f": {message}"
        super().__init__(full_msg)
        self.code = "CHANNEL_SEND_ERROR"


class ChannelConfigError(NotificationError):
    """Raised when a notification channel is misconfigured."""

    def __init__(self, channel_type: str, message: str = "") -> None:
        self.channel_type = channel_type
        full_msg = f"Channel {channel_type} misconfigured"
        if message:
            full_msg += f": {message}"
        super().__init__(full_msg)
        self.code = "CHANNEL_CONFIG_ERROR"


# ─── Authentication & Authorization ───


class AuthError(AppError):
    """Base exception for auth errors."""

    def __init__(self, message: str = "Authentication error") -> None:
        super().__init__(message, code="AUTH_ERROR")


class PermissionDeniedError(AuthError):
    """Raised when user lacks required permissions."""

    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(message)
        self.code = "PERMISSION_DENIED"


# ─── Encryption ───


class EncryptionError(AppError):
    """Raised when encryption/decryption fails."""

    def __init__(self, message: str = "Encryption error") -> None:
        super().__init__(message, code="ENCRYPTION_ERROR")
