"""
CS2 Instant Alert — FastAPI Application.

Creates and configures the FastAPI instance with CORS,
error handlers, and route registration.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import set_db_manager
from app.api.routes import health
from app.core.config import AppSettings, get_settings
from app.core.container import Container
from app.core.exceptions import AppError, EntityNotFoundError, PermissionDeniedError
from app.core.logging import get_logger, setup_logging
from app.database.session import DatabaseSessionManager

logger = get_logger("system")


from datetime import UTC, datetime

STARTUP_TIME: datetime | None = None


def create_api_app(
    settings: AppSettings | None = None,
    db_manager: DatabaseSessionManager | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        settings: Application settings (uses default if None).
        db_manager: Database session manager (creates one if None).
    """
    if settings is None:
        settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan: startup and shutdown."""
        global STARTUP_TIME
        STARTUP_TIME = datetime.now(UTC)

        # Startup
        setup_logging(
            log_level=settings.app_log_level,
            json_format=settings.is_production,
        )
        await logger.ainfo("api_startup", env=settings.app_env)

        _db = db_manager or DatabaseSessionManager(settings)
        await _db.initialize()
        set_db_manager(_db)

        # Initialize DI Container
        container = Container(config=settings, db_manager=_db)
        app.container = container  # type: ignore

        # Older builds created Telegram users without a subscription or channel,
        # making production alerts silently fan out to nobody. Repair those rows
        # on every startup; the operation is idempotent.
        async with _db.session() as session:
            from app.services.user_onboarding import backfill_existing_user_defaults

            repaired_users = await backfill_existing_user_defaults(session, settings)
        await logger.ainfo("user_notification_defaults_ready", users=repaired_users)

        # Start core background services
        await container.steam_client().initialize()
        container.event_bus().start()

        # Subscribe PatchNotesService
        from app.events.types import UpdateDetectedEvent
        container.event_bus().subscribe(
            UpdateDetectedEvent,
            container.patch_notes_service().start_polling_for_update
        )

        await container.notification_manager().start()
        await container.retry_engine().start()
        await container.orchestrator().start()
        await container.watchdog_service().start()

        # Start Telegram Bot
        from app.bot.application import build_application
        bot_app = build_application(container)
        if bot_app:
            await bot_app.initialize()
            await bot_app.start()
            if bot_app.updater:
                await bot_app.updater.start_polling()
            app.state.bot_app = bot_app

        # Startup Recovery
        await container.patch_notes_service().recover_pending_updates()

        # Self-Test
        health_service = container.health_service()
        await health_service.run_startup_self_test()

        await logger.ainfo("database_connected")
        await logger.ainfo("ApplicationStarted", version=settings.version)

        # Send Startup Summary
        metrics = await container.metrics_service().get_metrics()
        health = await health_service.check_all()

        async with container.db_manager().session() as session:
            from app.repositories.steam_state_repository import SteamStateRepository
            from app.repositories.game_repository import GameRepository
            game_repo = GameRepository(session)
            game = await game_repo.get_by_steam_app_id(730)
            
            state_repo = SteamStateRepository(session)
            app_state = await state_repo.get_or_create(game.id) if game else None

            # Count unacknowledged criticals & active retry tasks
            from sqlalchemy import func, select

            from app.models.notification_history import NotificationHistory
            from app.models.subscription import Subscription
            from app.models.update import Update
            
            unack_stmt = select(func.count(NotificationHistory.id)).join(Update).join(
                Subscription,
                (Subscription.user_id == NotificationHistory.user_id) & (Subscription.game_id == Update.game_id)
            ).where(
                Subscription.critical_enabled == True,
                NotificationHistory.acknowledged_at.is_(None),
                NotificationHistory.status == "delivered"
            )
            unack_count = await session.scalar(unack_stmt) or 0

            retry_stmt = select(func.count(NotificationHistory.id)).where(
                NotificationHistory.status == "pending_retry"
            )
            retry_count = await session.scalar(retry_stmt) or 0
            active_retries = await session.scalar(retry_stmt) or 0

        last_check = "N/A"
        last_build = "N/A"
        race_mode_text = "OFF"
        
        if app_state:
            last_check = app_state.last_check_at.strftime("%Y-%m-%d %H:%M:%S UTC") if app_state.last_check_at else "N/A"
            last_build = app_state.last_build_id or "N/A"
            race_mode_text = "ON" if app_state.race_mode_active else "OFF"
            
        summary = (
            f"🚀 *CS2 Instant Alert started*\n\n"
            f"*Version:* {settings.version}\n"
            f"*Uptime:* {metrics['uptime_seconds']:.1f}s\n\n"
            f"*Steam:* {'🟢 Connected' if health['steam_client'] else '🔴 Error'}\n"
            f"*Database:* {'🟢 Connected' if health['database'] else '🔴 Error'}\n"
            f"*Telegram:* {'🟢 Connected' if health['telegram_bot'] else '🔴 Error'}\n\n"
            f"*Race Mode:* {race_mode_text}\n"
            f"*Current BuildID:* {last_build}\n"
            f"*Last Check:* {last_check}\n\n"
            f"*Unacknowledged Critical:* {unack_count}\n"
            f"*Active Retry Tasks:* {active_retries}\n\n"
            f"*Health:* {'OK' if health['overall'] else 'Issues Detected'}"
        )
        await container.admin_notifier_service().broadcast(summary)

        yield

        # Shutdown
        await container.watchdog_service().stop()
        await container.patch_notes_service().stop()
        await container.orchestrator().stop()
        await container.retry_engine().stop()
        await container.event_bus().stop()
        await container.multi_source_monitor().close()
        await container.steam_client().close()

        await _db.close()
        
        bot_app = getattr(app.state, "bot_app", None)
        if bot_app:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        await logger.ainfo("api_shutdown")

    app = FastAPI(
        title="CS2 Instant Alert API",
        description="Steam update monitoring with multi-channel critical notifications",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # ─── Middleware ───
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Error Handlers ───
    @app.exception_handler(EntityNotFoundError)
    async def entity_not_found_handler(
        request: Request, exc: EntityNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(PermissionDeniedError)
    async def permission_denied_handler(
        request: Request, exc: PermissionDeniedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(AppError)
    async def app_error_handler(
        request: Request, exc: AppError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": exc.code, "message": exc.message},
        )

    # ─── Routes ───
    app.include_router(health.router, prefix="/api")

    return app
