"""
CS2 Instant Alert — Structured Logging.

Uses structlog with separate log files per domain:
  - system.log    — application lifecycle, general events
  - steam.log     — Steam monitoring events
  - notifications.log — notification dispatch events
  - telegram.log  — Telegram bot events
  - errors.log    — all ERROR+ level events (aggregate)

All logs are also output to stdout for Docker compatibility.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path

import structlog

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

# Domain logger names
LOGGER_SYSTEM = "system"
LOGGER_STEAM = "steam"
LOGGER_NOTIFICATIONS = "notifications"
LOGGER_TELEGRAM = "telegram"
LOGGER_ERRORS = "errors"

_LOG_FILES: dict[str, str] = {
    LOGGER_SYSTEM: "system.log",
    LOGGER_STEAM: "steam.log",
    LOGGER_NOTIFICATIONS: "notifications.log",
    LOGGER_TELEGRAM: "telegram.log",
    LOGGER_ERRORS: "errors.log",
}


class SensitiveDataFilter(logging.Filter):
    """Redact bot credentials if a dependency accidentally logs request URLs."""

    _telegram_token = re.compile(
        r"(?P<prefix>https://api\.telegram\.org/(?:file/)?bot)[0-9]+:[A-Za-z0-9_-]+"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._telegram_token.sub(r"\g<prefix><redacted>", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._telegram_token.sub(r"\g<prefix><redacted>", value)
                if isinstance(value, str)
                else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: self._telegram_token.sub(r"\g<prefix><redacted>", value)
                if isinstance(value, str)
                else value
                for key, value in record.args.items()
            }
        return True


def _ensure_log_dir() -> None:
    """Create log directory if it does not exist."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(log_level: str = "INFO", json_format: bool = False) -> None:
    """
    Configure structured logging for the entire application.

    Args:
        log_level: Root log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: If True, output JSON lines (for production). Otherwise, console-friendly.
    """
    _ensure_log_dir()

    # ─── Structlog Processors ───
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ─── Formatter for stdlib handlers ───
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    # ─── Root Logger ───
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Stdout handler (for Docker / console)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    stdout_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(stdout_handler)

    # ─── Domain-specific file handlers ───
    for logger_name, filename in _LOG_FILES.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        logger.propagate = True  # Also go to root (stdout)

        file_handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / filename,
            maxBytes=50 * 1024 * 1024,  # 50 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)
        file_handler.addFilter(SensitiveDataFilter())

        if logger_name == LOGGER_ERRORS:
            file_handler.setLevel(logging.ERROR)
        else:
            file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        logger.addHandler(file_handler)

    # ─── Error aggregate: capture all ERROR+ from root ───
    error_file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / _LOG_FILES[LOGGER_ERRORS],
        maxBytes=50 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(json_formatter)
    error_file_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(error_file_handler)

    # ─── Suppress noisy third-party loggers ───
    for noisy_logger in (
        "httpx",
        "httpcore",
        "asyncio",
        "aiosqlite",
        "telegram.ext.Application",
        "telegram.ext.ExtBot",
        "telegram.Bot",
        "SteamClient",
        "Connection",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str = LOGGER_SYSTEM) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger for the given domain.

    Args:
        name: Logger domain name (use LOGGER_* constants).

    Returns:
        A structlog BoundLogger instance.
    """
    return structlog.get_logger(name)
