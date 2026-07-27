"""
CS2 Instant Alert — Metrics Service.

Aggregates statistics about the system's operation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

STARTUP_TIME = datetime.now(UTC)

from app.models.notification_history import NotificationHistory
from app.models.update import Update


class MetricsService:
    """Calculates and aggregates system metrics."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def get_metrics(self) -> dict:
        """Get aggregate system statistics."""
        now = datetime.now(UTC)
        uptime_seconds = (now - STARTUP_TIME).total_seconds() if STARTUP_TIME else 0

        async with self.session_factory() as session:
            # Updates count
            updates_count = await session.scalar(select(func.count(Update.id)))

            # Last update
            last_update = await session.scalar(
                select(Update.detected_at).order_by(Update.detected_at.desc()).limit(1)
            )

            # Notifications count
            sent_count = await session.scalar(
                select(func.count(NotificationHistory.id))
                .where(NotificationHistory.status == "delivered")
            )

            # Errors count
            errors_count = await session.scalar(
                select(func.count(NotificationHistory.id))
                .where(NotificationHistory.status == "failed")
            )

            # Avg delivery time
            avg_latency = await session.scalar(
                select(func.avg(NotificationHistory.latency_ms))
            )

        return {
            "uptime_seconds": uptime_seconds,
            "updates_found": updates_count or 0,
            "last_update": last_update.isoformat() if last_update else None,
            "notifications_sent": sent_count or 0,
            "errors": errors_count or 0,
            "avg_delivery_latency_ms": round(avg_latency, 2) if avg_latency else None,
        }
