"""
CS2 Instant Alert — Silent Watchdog Service.

Monitors Steam connection health and alerts the admin if it stays down.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.steam.client import AsyncSteamClient

if TYPE_CHECKING:
    from app.services.admin_notifier import AdminNotifierService
    from app.services.health_service import HealthService

logger = get_logger("system")


class SilentWatchdogService:
    """Monitors all components and sends critical alerts/restarts if down."""

    def __init__(
        self,
        steam_client: AsyncSteamClient,
        settings: AppSettings,
        health_service: 'HealthService',
        admin_notifier: 'AdminNotifierService' | None = None,
    ) -> None:
        self.steam_client = steam_client
        self.settings = settings
        self.health_service = health_service
        self.admin_notifier = admin_notifier
        self._running = False
        self._task: asyncio.Task | None = None
        self._alert_active = False
        self._last_alert_time: datetime | None = None
        
        self._system_downtime_start: datetime | None = None

    async def start(self) -> None:
        """Start the watchdog."""
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="SilentWatchdog")
        await logger.ainfo("watchdog_started")

    async def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        try:
            while self._running:
                await self._check_health()
                await asyncio.sleep(60)  # Check every minute
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await logger.aerror("watchdog_crashed", error=str(e), exc_info=True)

    async def _check_health(self) -> None:
        now = datetime.now(UTC)
        
        # 1. System-wide check
        status = await self.health_service.check_all()
        if not status.get("overall", False):
            failed_components = [k for k, v in status.items() if not v and k != "overall"]
            if not self._system_downtime_start:
                self._system_downtime_start = now
                await logger.awarning("system_components_failed", failed=failed_components)
                
            downtime_minutes = (now - self._system_downtime_start).total_seconds() / 60.0

            # Only restart if internal critical services (database, event_bus, scheduler) are failing.
            # Steam downtime is an external event and handled via alerts/auto-reconnect in section 2.
            internal_critical = [c for c in failed_components if c in {"database", "event_bus", "scheduler"}]
            if internal_critical and downtime_minutes >= 10.0:
                message = (
                    f"⚠️ Критическая ошибка!\n\n"
                    f"Внутренние компоненты ({', '.join(internal_critical)}) не отвечают более 10 минут.\n"
                    f"Инициирован принудительный перезапуск контейнера для восстановления связи."
                )
                await logger.acritical("SystemDowntimeTooLong", failed=internal_critical, minutes=int(downtime_minutes), action="os._exit(1)")
                if self.admin_notifier and status.get("telegram_bot", False):
                    # Only try to broadcast if TG bot is healthy
                    try:
                        await self.admin_notifier.broadcast(message)
                        await asyncio.sleep(2)
                    except Exception:
                        pass
                os._exit(1)
        else:
            if self._system_downtime_start:
                self._system_downtime_start = None
                await logger.ainfo("system_components_recovered")

        # 2. Steam-specific alerting (non-restarting logic, just admin alerts)
        is_connected = self.steam_client._connected.is_set()

        if is_connected:
            if self._alert_active:
                self._alert_active = False
                self._last_alert_time = None
                await logger.ainfo("SteamReconnected")
                if self.admin_notifier and status.get("telegram_bot", False):
                    last_success = self.steam_client.last_successful_connection
                    last_success_str = last_success.strftime('%Y-%m-%d %H:%M:%S UTC') if last_success else "N/A"
                    steam_downtime_minutes = self.steam_client.downtime_duration / 60.0

                    msg = (
                        "✅ <b>Steam connection restored.</b>\n\n"
                        f"<b>Downtime:</b> {int(steam_downtime_minutes)} min\n"
                        f"<b>Reconnect attempts:</b> {self.steam_client.consecutive_failed_attempts}\n"
                        f"<b>Last successful check:</b> {last_success_str}\n"
                        f"<b>Reason:</b> {self.steam_client.disconnect_reason or 'Unknown'}"
                    )
                    await self.admin_notifier.broadcast(msg)
            return

        # If not connected, check how long it's been down
        disconnect_time = self.steam_client.disconnect_time or self._system_downtime_start
        if not disconnect_time:
            return

        steam_downtime_minutes = (now - disconnect_time).total_seconds() / 60.0

        if steam_downtime_minutes >= 2.0:
            if self._last_alert_time:
                time_since_last_alert = (now - self._last_alert_time).total_seconds() / 60.0
                if time_since_last_alert < 10.0:
                    return # Wait for next 10 minute interval

            self._alert_active = True
            self._last_alert_time = now

            # Automatic self-healing: restart steam client if down for >= 5 minutes
            await logger.awarning("steam_watchdog_triggering_self_heal", minutes=int(steam_downtime_minutes))
            try:
                await self.steam_client.restart()
            except Exception as e:
                await logger.aerror("steam_watchdog_self_heal_error", error=str(e))

            message = (
                f"⚠️ Внимание!\n\n"
                f"Мониторинг Steam остановлен.\n"
                f"Последняя успешная проверка: {int(steam_downtime_minutes)} минут назад.\n"
                f"Причина: {self.steam_client.disconnect_reason or 'Неизвестно'}\n"
                f"Попыток переподключения: {self.steam_client.consecutive_failed_attempts}\n\n"
                f"Инициирован автоматический перезапуск подсистемы Steam."
            )

            await logger.acritical("SteamDisconnected", minutes=int(steam_downtime_minutes))
            if self.admin_notifier and status.get("telegram_bot", False):
                await self.admin_notifier.broadcast(message)
