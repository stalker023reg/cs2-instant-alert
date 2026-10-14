"""
CS2 Instant Alert — Async Steam Client Wrapper.

Wraps the synchronous/gevent-based `steam` library in an
async-friendly interface using a background thread and asyncio.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import queue
import threading
from datetime import UTC
from typing import Any, Callable, TypeVar

import gevent
from gevent.hub import Hub

from app.core.config import AppSettings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from steam.client import SteamClient

logger = get_logger("steam")

T = TypeVar("T")


class SteamConnectionError(AppError):
    """Raised when Steam connection fails."""
    pass


class AsyncSteamClient:
    """
    Asynchronous wrapper around the `steam` library.
    
    Since `steam` uses gevent internally, we isolate it in a dedicated thread
    and provide async methods to interact with it safely from the main asyncio loop.
    """

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.client: SteamClient | None = None

        # We don't want the SteamClient to spam stdout with its own gevent logs
        import logging
        logging.getLogger("steam").setLevel(logging.WARNING)

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._gevent_hub: Hub | None = None
        self._connected = asyncio.Event()
        self._startup_failed = asyncio.Event()
        self._stop_requested = threading.Event()
        self._thread_error: str | None = None

        # Task queue for cross-thread operation dispatch
        self._task_queue: queue.Queue[tuple[Callable, concurrent.futures.Future]] = queue.Queue()

        # Metrics
        from datetime import datetime
        self.last_successful_connection: datetime | None = None
        self.disconnect_reason: str | None = None
        self.disconnect_time: datetime | None = None
        self.reconnect_time: datetime | None = None
        self.downtime_duration: float = 0.0
        self.consecutive_failed_attempts: int = 0

    async def initialize(self) -> None:
        """Initialize the client and start the background thread."""
        self._loop = asyncio.get_running_loop()
        self._connected.clear()
        self._startup_failed.clear()
        self._stop_requested.clear()
        self._thread_error = None

        # Start the background thread that runs the Steam client
        self._thread = threading.Thread(
            target=self._run_steam_client,
            daemon=True,
            name="SteamClientThread",
        )
        self._thread.start()

        # Wait for a successful login or a terminal startup failure.
        connected_waiter = asyncio.create_task(self._connected.wait())
        failed_waiter = asyncio.create_task(self._startup_failed.wait())
        try:
            done, pending = await asyncio.wait(
                {connected_waiter, failed_waiter},
                timeout=15.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for waiter in pending:
                waiter.cancel()

            if not done:
                raise TimeoutError
            if self._startup_failed.is_set():
                raise SteamConnectionError(
                    f"Steam client thread failed: {self._thread_error or 'unknown error'}",
                    code="STEAM_THREAD_FAILED",
                )

            await logger.ainfo("steam_client_initialized", anonymous=self.settings.steam_anonymous_login)
        except TimeoutError:
            self.consecutive_failed_attempts += 1
            raise SteamConnectionError("Timeout waiting for Steam to connect", code="STEAM_TIMEOUT")
        finally:
            for waiter in (connected_waiter, failed_waiter):
                if not waiter.done():
                    waiter.cancel()

    def _setup_client_handlers(self) -> None:
        """Register event handlers on self.client."""
        from datetime import datetime

        @self.client.on("logged_on")
        def handle_logged_on() -> None:
            if self._loop:
                self._loop.call_soon_threadsafe(self._connected.set)

            now = datetime.now(UTC)
            self.last_successful_connection = now
            self.reconnect_time = now
            if self.disconnect_time:
                self.downtime_duration = (now - self.disconnect_time).total_seconds()
            self.consecutive_failed_attempts = 0
            self.disconnect_reason = None

        @self.client.on("disconnected")
        def handle_disconnected(result=None) -> None:
            if self._loop:
                self._loop.call_soon_threadsafe(self._connected.clear)

            now = datetime.now(UTC)
            self.disconnect_time = now
            self.consecutive_failed_attempts += 1
            self.disconnect_reason = str(result) if result else "Unknown"

            if self._loop:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(
                        logger.awarning("steam_disconnected", reason=self.disconnect_reason, attempts=self.consecutive_failed_attempts)
                    )
                )
            # Client auto-reconnects by default

    def _run_steam_client(self) -> None:
        """Runs in the background thread."""
        try:
            # The steam package is gevent-based. Its hub and every blocking Steam
            # operation must live in this one thread; crossing hubs causes
            # ``Invalid switch into AsyncResult.wait()`` at runtime.
            self._gevent_hub = gevent.get_hub()
            self.client = SteamClient()
            self._setup_client_handlers()

            # Connect and log in (retry loop with strict timeout to prevent hangs on dead CM servers)
            fail_count = 0
            while not self._stop_requested.is_set():
                try:
                    # Enforce a 15s timeout per login attempt so dead CM servers cannot block the thread
                    with gevent.Timeout(15.0, False):
                        if self.settings.steam_anonymous_login:
                            self.client.anonymous_login()
                        else:
                            self.client.login(
                                username=self.settings.steam_username,
                                password=self.settings.steam_password,
                            )
                    if self.client.logged_on:
                        break

                    fail_count += 1
                    self.consecutive_failed_attempts += 1
                    self.disconnect_reason = "Login timed out or failed"

                    # Disconnect any hanging or half-open socket
                    try:
                        self.client.disconnect()
                    except Exception:
                        pass

                    # Re-instantiate SteamClient to refresh CM server list from WebAPI if repeatedly failing
                    if fail_count >= 3:
                        try:
                            self.client = SteamClient()
                            self._setup_client_handlers()
                            fail_count = 0
                        except Exception:
                            pass

                except Exception as login_err:
                    self.consecutive_failed_attempts += 1
                    self.disconnect_reason = str(login_err)
                    try:
                        self.client.disconnect()
                    except Exception:
                        pass

                if self._stop_requested.is_set():
                    return
                self.client.sleep(5.0)

            # Main loop: pump gevent hub, process queued tasks, and auto-reconnect
            import time as _time
            last_heartbeat = _time.monotonic()
            reconnect_delay = 5.0   # seconds; grows with exponential backoff
            reconnect_failures = 0

            while not self._stop_requested.is_set():
                # Process any pending tasks from the async side
                self._drain_task_queue()

                if not self.client.logged_on:
                    # ── Auto-reconnect within the Steam thread ──
                    if self._loop:
                        _delay = reconnect_delay
                        self._loop.call_soon_threadsafe(
                            lambda d=_delay: asyncio.create_task(
                                logger.awarning("steam_auto_reconnecting", delay=d)
                            )
                        )

                    self.client.sleep(reconnect_delay)
                    if self._stop_requested.is_set():
                        break

                    try:
                        # Re-create client after 3 consecutive failures (stale CM list)
                        if reconnect_failures >= 3:
                            try:
                                self.client = SteamClient()
                                self._setup_client_handlers()
                                reconnect_failures = 0
                            except Exception:
                                pass

                        with gevent.Timeout(15.0, False):
                            if self.settings.steam_anonymous_login:
                                self.client.anonymous_login()
                            else:
                                self.client.login(
                                    username=self.settings.steam_username,
                                    password=self.settings.steam_password,
                                )

                        if self.client.logged_on:
                            reconnect_delay = 5.0
                            reconnect_failures = 0
                        else:
                            reconnect_failures += 1
                            reconnect_delay = min(reconnect_delay * 2, 60.0)
                            try:
                                self.client.disconnect()
                            except Exception:
                                pass
                    except Exception:
                        reconnect_failures += 1
                        reconnect_delay = min(reconnect_delay * 2, 60.0)
                        try:
                            self.client.disconnect()
                        except Exception:
                            pass
                else:
                    reconnect_delay = 5.0
                    reconnect_failures = 0
                    # Give gevent a chance to process its events (heartbeats etc.)
                    self.client.sleep(0.5)

                # ── Heartbeat every 5 minutes for observability ──
                now_mono = _time.monotonic()
                if now_mono - last_heartbeat >= 300:
                    last_heartbeat = now_mono
                    _is_on = self.client.logged_on
                    if self._loop:
                        self._loop.call_soon_threadsafe(
                            lambda c=_is_on: asyncio.create_task(
                                logger.ainfo("steam_heartbeat", connected=c)
                            )
                        )

        except Exception as e:
            self._thread_error = str(e)
            if self._loop:
                error_msg = str(e)
                self._loop.call_soon_threadsafe(
                    self._startup_failed.set
                )
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(logger.aerror("steam_thread_crashed", error=error_msg))
                )
        finally:
            self._gevent_hub = None

    def _drain_task_queue(self) -> None:
        """Process all pending tasks from the queue. Runs inside the Steam thread.
        
        Each operation is spawned as a gevent greenlet so that blocking Steam
        calls (like get_product_info) can yield to the hub for I/O processing.
        """
        while True:
            try:
                operation, future = self._task_queue.get_nowait()
            except queue.Empty:
                break

            if future.cancelled():
                continue

            def _execute(op: Callable, fut: concurrent.futures.Future) -> None:
                try:
                    result = op()
                    fut.set_result(result)
                except BaseException as exc:
                    fut.set_exception(exc)

            gevent.spawn(_execute, operation, future)

    async def close(self) -> None:
        """Close the Steam connection and background thread."""
        if self.client and self._gevent_hub and self._thread and self._thread.is_alive():
            try:
                if self.client.logged_on:
                    await self._run_in_steam_thread(self.client.logout, timeout=10.0)
                elif self.client.connected:
                    await self._run_in_steam_thread(self.client.disconnect, timeout=5.0)
            except SteamConnectionError as exc:
                await logger.awarning("steam_client_close_failed", error=str(exc))

        self._stop_requested.set()
        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 5.0)

        await logger.ainfo("steam_client_closed")

    async def restart(self) -> None:
        """Restart the Steam client thread and reconnect (used for watchdog self-healing)."""
        await logger.ainfo("steam_client_restart_requested")
        await self.close()

        self._stop_requested.clear()
        self._connected.clear()
        self._startup_failed.clear()
        self._thread_error = None
        self._task_queue = queue.Queue()

        self._thread = threading.Thread(
            target=self._run_steam_client,
            daemon=True,
            name="SteamClientThread",
        )
        self._thread.start()

        try:
            connected_waiter = asyncio.create_task(self._connected.wait())
            await asyncio.wait_for(connected_waiter, timeout=15.0)
            await logger.ainfo("steam_client_restarted_successfully")
        except TimeoutError:
            await logger.awarning("steam_client_restart_connect_pending")

    async def _run_in_steam_thread(
        self,
        operation: Callable[[], T],
        *,
        timeout: float = 30.0,
    ) -> T:
        """Execute a gevent/Steam operation on the Steam client's own hub.
        
        Places the operation on a task queue that is drained by the Steam
        thread's main loop, ensuring all gevent calls happen in the correct
        hub/thread context.
        """
        if not self._gevent_hub or not self._thread or not self._thread.is_alive():
            raise SteamConnectionError("Steam client thread is not running", code="STEAM_THREAD_STOPPED")

        future: concurrent.futures.Future[T] = concurrent.futures.Future()
        self._task_queue.put((operation, future))

        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
        except TimeoutError as exc:
            future.cancel()
            raise SteamConnectionError(
                "Timed out waiting for Steam operation",
                code="STEAM_OPERATION_TIMEOUT",
            ) from exc

    async def get_product_info(self, apps: list[int], packages: list[int] | None = None) -> dict[str, Any]:
        """
        Fetch product info (PICS) asynchronously.
        """
        if not self._connected.is_set():
            raise SteamConnectionError("Steam client is not connected", code="STEAM_NOT_CONNECTED")

        packages = packages or []

        def _fetch() -> dict[str, Any]:
            if not self.client:
                raise SteamConnectionError("Steam client is not initialized", code="STEAM_NOT_INITIALIZED")
            return self.client.get_product_info(apps=apps, packages=packages)  # type: ignore

        try:
            return await self._run_in_steam_thread(_fetch, timeout=30.0)
        except Exception as e:
            await logger.aerror("pics_fetch_failed", apps=apps, error=str(e))
            raise SteamConnectionError(f"Failed to fetch product info: {e}", code="PICS_ERROR") from e

