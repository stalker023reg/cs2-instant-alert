"""
CS2 Instant Alert — Dependency Injection Container.

Uses dependency-injector to wire all services, repositories,
and infrastructure components.
"""

from __future__ import annotations

from dependency_injector import containers, providers

from app.core.config import AppSettings
from app.core.security import CredentialEncryptor
from app.database.session import DatabaseSessionManager
from app.events.bus import EventBus
from app.notifications.acknowledgement import AcknowledgementService
from app.notifications.channels.telegram import TelegramChannel
from app.notifications.dispatcher import NotificationDispatcher
from app.notifications.manager import NotificationManager
from app.notifications.retry_engine import RetryEngine
from app.scheduler.tasks import MonitoringOrchestrator
from app.services.admin_notifier import AdminNotifierService
from app.services.health_service import HealthService
from app.services.metrics_service import MetricsService
from app.services.patch_notes_service import PatchNotesService
from app.services.translation_service import TranslationService
from app.services.watchdog import SilentWatchdogService
from app.steam.client import AsyncSteamClient
from app.steam.multi_source_monitor import MultiSourceMonitor
from app.steam.pics_monitor import PICSMonitor
from app.steam.store_monitor import StoreMonitor
from app.steam.webapi_monitor import WebAPIMonitor


class Container(containers.DeclarativeContainer):
    """
    Root DI container.

    All application components are wired here.
    Modules that depend on components not yet built (Steam, Notifications, Bot)
    will be added in their respective phases.
    """

    wiring_config = containers.WiringConfiguration(
        packages=["app.api", "app.bot"],
    )

    # ─── Configuration ───
    config = providers.Singleton(AppSettings)

    # ─── Infrastructure ───
    db_manager = providers.Singleton(
        DatabaseSessionManager,
        settings=config,
    )

    encryptor = providers.Singleton(
        CredentialEncryptor,
        encryption_key=config.provided.encryption_key,
    )

    # ─── Repositories ───
    # Repositories are created per-request (need a session from db_manager).
    # They will be injected via FastAPI dependencies and bot middleware.
    # Actual wiring happens in api/dependencies.py and bot/middleware/auth.py.

    # ─── Events ───
    event_bus = providers.Singleton(EventBus)

    # ─── Services ───
    # Will be added in Phase 3 when services are implemented.

    # ─── Steam ───
    steam_client = providers.Singleton(
        AsyncSteamClient,
        settings=config,
    )

    pics_monitor = providers.Singleton(
        PICSMonitor,
        steam_client=steam_client,
    )

    webapi_monitor = providers.Singleton(
        WebAPIMonitor,
        settings=config,
    )

    store_monitor = providers.Singleton(
        StoreMonitor,
    )

    multi_source_monitor = providers.Singleton(
        MultiSourceMonitor,
        pics_monitor=pics_monitor,
        webapi_monitor=webapi_monitor,
        store_monitor=store_monitor,
        settings=config,
    )

    # ─── Notifications ───
    telegram_channel = providers.Singleton(
        TelegramChannel,
        settings=config,
    )

    # Dictionary of available channels
    notification_channels = providers.Dict({
        "telegram": telegram_channel,
    })

    notification_dispatcher = providers.Singleton(
        NotificationDispatcher,
        channels=notification_channels,
        session_factory=db_manager.provided.session,
    )

    notification_manager = providers.Singleton(
        NotificationManager,
        session_factory=db_manager.provided.session,
        event_bus=event_bus,
        dispatcher=notification_dispatcher,
        settings=config,
    )

    retry_engine = providers.Singleton(
        RetryEngine,
        session_factory=db_manager.provided.session,
        channels=notification_channels,
        settings=config,
    )

    acknowledgement_service = providers.Singleton(
        AcknowledgementService,
        session_factory=db_manager.provided.session,
        event_bus=event_bus,
    )

    # ─── Scheduler ───
    orchestrator = providers.Singleton(
        MonitoringOrchestrator,
        session_factory=db_manager.provided.session,
        monitor=multi_source_monitor,
        event_bus=event_bus,
        settings=config,
    )

    # ─── System Services ───
    health_service = providers.Singleton(
        HealthService,
        session_factory=db_manager.provided.session,
        steam_client=steam_client,
        event_bus=event_bus,
        orchestrator=orchestrator,
        settings=config,
    )

    metrics_service = providers.Singleton(
        MetricsService,
        session_factory=db_manager.provided.session,
    )

    translation_service = providers.Singleton(
        TranslationService,
        api_key=config.provided.deepl_api_key,
    )

    patch_notes_service = providers.Singleton(
        PatchNotesService,
        session_factory=db_manager.provided.session,
        telegram_channel=telegram_channel,
        settings=config,
        translation_service=translation_service,
    )

    admin_notifier_service = providers.Singleton(
        AdminNotifierService,
        session_factory=db_manager.provided.session,
        telegram_channel=telegram_channel,
        settings=config,
    )

    watchdog_service = providers.Singleton(
        SilentWatchdogService,
        steam_client=steam_client,
        settings=config,
        health_service=health_service,
        admin_notifier=admin_notifier_service,
    )
