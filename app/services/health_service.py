"""
CS2 Instant Alert — Health Service.

Checks the status of various system components (Steam, PostgreSQL,
Redis, Telegram Bot, EventBus, Scheduler).
Used for boot-time self-tests and the /status command.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text

from app.core.config import AppSettings
from app.core.logging import get_logger
from app.events.bus import EventBus
from app.models.steam_app_state import SteamAppState
from app.scheduler.tasks import MonitoringOrchestrator
from app.steam.client import AsyncSteamClient

logger = get_logger("system")


class HealthService:
    """Service to check the health of system components."""

    def __init__(
        self,
        session_factory,
        steam_client: AsyncSteamClient,
        event_bus: EventBus,
        orchestrator: MonitoringOrchestrator,
        settings: AppSettings,
    ) -> None:
        self.session_factory = session_factory
        self.steam_client = steam_client
        self.event_bus = event_bus
        self.orchestrator = orchestrator
        self.settings = settings

    async def check_all(self) -> dict[str, Any]:
        """Run all health checks and return the status dictionary."""
        status = {
            "database": await self._check_database(),
            "steam_client": await self._check_steam_client(),
            "telegram_bot": await self._check_telegram_bot(),
            "event_bus": self._check_event_bus(),
            "scheduler": self._check_scheduler(),
            "monitoring_fresh": await self._check_monitoring_freshness(),
        }

        # Redis is optional
        if self.settings.redis_host:
            status["redis"] = await self._check_redis()

        status["overall"] = all(v for k, v in status.items() if k != "overall")
        return status

    async def run_startup_self_test(self) -> None:
        """
        Run critical health checks on startup.
        If a critical component fails, transition to safe mode or exit.
        """
        await logger.ainfo("running_startup_self_test")
        status = await self.check_all()

        failed = [k for k, v in status.items() if not v and k != "overall"]

        if failed:
            await logger.acritical("startup_self_test_failed", failed_components=failed)
            # Notify admin if TG is up, otherwise just exit.
            if status.get("telegram_bot"):
                await self._notify_admin_safe_mode(failed)

            # If the primary database fails, the app cannot operate.
            if "database" in failed:
                sys.exit("Critical database component failed self-test. Exiting.")
        else:
            await logger.ainfo("startup_self_test_passed")

    async def _check_database(self) -> bool:
        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            await logger.aerror("healthcheck_db_failed", error=str(e))
            return False

    async def _check_steam_client(self) -> bool:
        if not self.steam_client.client or not getattr(self.steam_client.client, "connected", False):
            return False
        return True

    async def _check_telegram_bot(self) -> bool:
        token = self.settings.telegram_bot_token.get_secret_value()
        if not token:
            return False

        try:
            from telegram import Bot
            bot = Bot(token=token)
            me = await bot.get_me()
            return bool(me)
        except Exception as e:
            await logger.aerror("healthcheck_tg_failed", error=str(e))
            return False

    def _check_event_bus(self) -> bool:
        return self.event_bus._task is not None and not self.event_bus._task.done()

    def _check_scheduler(self) -> bool:
        return self.orchestrator._running and any(
            not task.done() for task in self.orchestrator._tasks.values()
        )

    async def _check_monitoring_freshness(self) -> bool:
        """Verify that a successful PICS result recently reached the database."""
        try:
            async with self.session_factory() as session:
                last_check = await session.scalar(select(func.max(SteamAppState.last_check_at)))
            if last_check is None:
                return False
            max_age_seconds = max(60, self.settings.steam_check_interval_seconds * 4)
            return (datetime.now(UTC) - last_check).total_seconds() <= max_age_seconds
        except Exception as e:
            await logger.aerror("healthcheck_monitoring_failed", error=str(e))
            return False

    async def _check_redis(self) -> bool:
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                self.settings.redis_url,
                decode_responses=True,
            )
            try:
                return await client.ping()
            finally:
                await client.aclose()
        except ImportError:
            return True
        except Exception as e:
            await logger.aerror("healthcheck_redis_failed", error=str(e))
            return False

    async def _notify_admin_safe_mode(self, failed: list[str]) -> None:
        """Attempt to message admins that system booted in safe mode."""
        token = self.settings.telegram_bot_token.get_secret_value()
        if not token or not self.settings.telegram_admin_ids:
            return

        try:
            from telegram import Bot
            bot = Bot(token=token)
            text = f"🚨 *CRITICAL ALERT* 🚨\n\nСистема загружена с ошибками. Компоненты: {', '.join(failed)}"
            for admin_id in self.settings.telegram_admin_ids:
                await bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
        except Exception:
            pass
