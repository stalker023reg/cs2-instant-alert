"""
CS2 Instant Alert — Generic Async Retry Decorator.

Provides configurable retry logic with exponential backoff
for network operations (Steam, notifications, etc.).
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import structlog

T = TypeVar("T")

logger = structlog.get_logger("system")


def async_retry(
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator for async functions that retries on failure with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        base_delay: Initial delay between retries (seconds).
        max_delay: Maximum delay between retries (seconds).
        exponential_base: Base for exponential backoff calculation.
        retryable_exceptions: Tuple of exception types to retry on.
    """

    def decorator(
        func: Callable[..., Coroutine[Any, Any, T]],
    ) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt == max_attempts:
                        await logger.aerror(
                            "retry_exhausted",
                            function=func.__name__,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            error=str(exc),
                        )
                        raise

                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay,
                    )
                    await logger.awarning(
                        "retry_attempt",
                        function=func.__name__,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)

            # Should never reach here, but satisfy type checker
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
