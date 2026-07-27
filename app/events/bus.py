"""
CS2 Instant Alert — Event Bus.

Internal Pub/Sub system for decoupling components.
Currently uses in-memory asyncio event routing. For horizontal
scaling, this can be swapped with a Redis Pub/Sub backend.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.logging import get_logger

logger = get_logger("system")

# Type variable for Event payloads
E = TypeVar("E", bound=BaseModel)

# Type alias for event handlers
EventHandler = Callable[[E], Awaitable[None]]


class EventBus:
    """
    Asynchronous event bus for internal messaging.
    """

    def __init__(self) -> None:
        self._subscribers: dict[type[BaseModel], list[EventHandler[Any]]] = defaultdict(list)
        self._queue: asyncio.Queue[BaseModel] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def subscribe(self, event_type: type[E], handler: EventHandler[E]) -> None:
        """Register a handler for a specific event type."""
        self._subscribers[event_type].append(handler)
        logger.debug("event_subscribed", event_type=event_type.__name__, handler=handler.__name__)

    async def publish(self, event: BaseModel) -> None:
        """Publish an event to the bus."""
        await self._queue.put(event)
        logger.debug("event_published", event_type=type(event).__name__)

    def start(self) -> None:
        """Start the event processing loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._process_events(), name="EventBus")

    async def stop(self) -> None:
        """Stop the event processing loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _process_events(self) -> None:
        """Background task to route events to handlers."""
        try:
            while True:
                event = await self._queue.get()
                event_type = type(event)
                handlers = self._subscribers.get(event_type, [])

                if not handlers:
                    logger.debug("event_unhandled", event_type=event_type.__name__)
                    self._queue.task_done()
                    continue

                # Run handlers concurrently without blocking the bus
                tasks = []
                for handler in handlers:
                    tasks.append(self._safe_handle(handler, event))

                if tasks:
                    # gather() returns a Future, not a coroutine —
                    # create_task() requires a coroutine, so we wrap it.
                    async def _dispatch(t=tasks):
                        await asyncio.gather(*t)
                    asyncio.create_task(_dispatch())

                self._queue.task_done()
        except asyncio.CancelledError:
            logger.info("event_bus_stopped")

    async def _safe_handle(self, handler: EventHandler[Any], event: BaseModel) -> None:
        """Execute a handler safely without crashing the bus."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                "event_handler_failed",
                event_type=type(event).__name__,
                handler=handler.__name__,
                error=str(e),
                exc_info=True,
            )
