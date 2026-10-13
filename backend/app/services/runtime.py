from __future__ import annotations

import logging

from app import __version__
from app.core.config import AppSettings
from app.core.rate_limit import InMemoryRateLimiter
from app.core.security import CredentialCipher
from app.persistence import Database

from .discovery import DiscoveryService
from .events import EventBroker
from .scheduler import RefreshScheduler

logger = logging.getLogger(__name__)


class AppRuntime:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.cipher = CredentialCipher.from_settings(
            settings.data_dir,
            settings.secret_key,
        )
        self.database = Database(
            settings.database_path,
            self.cipher,
            settings.default_refresh_seconds,
        )
        self.events = EventBroker()
        self.discovery = DiscoveryService(settings, self.database, self.events)
        self.scheduler = RefreshScheduler(self.database, self.discovery)
        self.rate_limiter = InMemoryRateLimiter()
        self.version = __version__

    async def start(self) -> None:
        logger.info(
            "SDEX ConnectMap starting",
            extra={"event": "startup", "status": self.version},
        )
        await self.database.initialize()
        logger.info(
            "SQLite schema ready",
            extra={
                "event": "database_migration",
                "status": await self.database.schema_version(),
            },
        )
        self.scheduler.start()

    async def stop(self) -> None:
        await self.scheduler.stop()
        await self.discovery.close()
        logger.info("SDEX ConnectMap stopped", extra={"event": "shutdown"})
