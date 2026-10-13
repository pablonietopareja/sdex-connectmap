from __future__ import annotations

import asyncio
import logging

from app.persistence import Database

from .discovery import DiscoveryService

logger = logging.getLogger(__name__)


class RefreshScheduler:
    def __init__(self, database: Database, discovery: DiscoveryService) -> None:
        self.database = database
        self.discovery = discovery
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._wake.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="connectmap-refresh-scheduler",
        )

    async def _run(self) -> None:
        logger.info("Refresh scheduler started", extra={"event": "scheduler_started"})
        try:
            if await self._safe_configured():
                await self._safe_refresh("startup")
            while not self._stop.is_set():
                try:
                    settings = await self.database.load_settings()
                    interval = settings.refresh_interval_seconds
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Refresh scheduler could not read settings; it will retry",
                        extra={"event": "scheduler_settings_error"},
                    )
                    interval = 30
                try:
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=interval,
                    )
                except TimeoutError:
                    if await self._safe_configured():
                        await self._safe_refresh("scheduled")
                else:
                    self._wake.clear()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Refresh scheduler encountered an unexpected error",
                extra={"event": "scheduler_error"},
            )
        finally:
            logger.info("Refresh scheduler stopped", extra={"event": "scheduler_stopped"})

    async def _safe_refresh(self, trigger: str) -> None:
        try:
            await self.discovery.refresh(trigger)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Scheduled topology refresh failed; the scheduler will continue",
                extra={"event": "scheduled_refresh_error", "status": trigger},
            )

    async def _safe_configured(self) -> bool:
        try:
            return await self.discovery.client_manager.configured()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Refresh scheduler could not resolve SDEX configuration; it will retry",
                extra={"event": "scheduler_configuration_error"},
            )
            return False

    def reschedule(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=10)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            self._task = None
