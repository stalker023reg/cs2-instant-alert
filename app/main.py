"""
CS2 Instant Alert — Application Entrypoint.

Orchestrates startup of all subsystems:
  1. Configuration & Logging
  2. Database connection
  3. FastAPI server
  4. (Phase 2+) Steam Monitor, Telegram Bot, Scheduler, etc.

Supports graceful shutdown via SIGINT/SIGTERM.
"""

from __future__ import annotations

import signal
import sys
from types import FrameType

import uvicorn

from app.api.app import create_api_app
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("system")


def handle_signal(signum: int, frame: FrameType | None) -> None:
    """Handle shutdown signals gracefully."""
    sig_name = signal.Signals(signum).name
    print(f"\n[{sig_name}] Shutting down gracefully...")
    sys.exit(0)


def main() -> None:
    """Application entrypoint."""
    settings = get_settings()

    # Logging is configured in create_api_app lifespan.
    # Do NOT call setup_logging() here — the lifespan calls
    # root_logger.handlers.clear() which would wipe any handlers
    # we set up here, and double-init can lose app-level messages.

    # Register signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Create FastAPI app
    app = create_api_app(settings=settings)

    # Run uvicorn
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        log_level=settings.app_log_level.lower(),
        access_log=not settings.is_production,
    )


if __name__ == "__main__":
    main()
