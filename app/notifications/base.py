"""
CS2 Instant Alert — Abstract Notification Channel.

Defines the base interface for all notification delivery methods
(Telegram, Pushover, Webhook, etc.).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from app.core.exceptions import AppError
from app.events.types import UpdateDetectedEvent
from app.models.notification_channel import NotificationChannel
from app.models.user import User


class ChannelDeliveryError(AppError):
    """Raised when a channel fails to deliver a notification."""
    pass


class AbstractNotificationChannel(ABC):
    """
    Base class for notification channels.
    """

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """The identifier of this channel type (e.g., 'telegram')."""
        pass

    @abstractmethod
    async def send_update_alert(
        self,
        user: User,
        channel_config: NotificationChannel,
        event: UpdateDetectedEvent,
        notification_id: uuid.UUID,
    ) -> str | None:
        """
        Send an alert for a detected update.
        Returns a provider-specific message ID, if applicable.
        
        Args:
            user: The recipient user.
            channel_config: The channel configuration (credentials, etc).
            event: The update event payload.
            notification_id: The unique ID of this delivery attempt (for tracking/acks).
            
        Raises:
            ChannelDeliveryError: If delivery fails.
        """
        pass
