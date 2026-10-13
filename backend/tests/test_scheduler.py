from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.scheduler import RefreshScheduler


class FakeDatabase:
    async def load_settings(self):
        return SimpleNamespace(refresh_interval_seconds=0.02)


class FakeClientManager:
    async def configured(self) -> bool:
        return True


class FlakyDiscovery:
    def __init__(self) -> None:
        self.client_manager = FakeClientManager()
        self.calls = 0
        self.called = asyncio.Event()

    async def refresh(self, _trigger: str):
        self.calls += 1
        self.called.set()
        raise RuntimeError("injected refresh failure")


@pytest.mark.asyncio
async def test_scheduler_survives_refresh_exception() -> None:
    discovery = FlakyDiscovery()
    scheduler = RefreshScheduler(FakeDatabase(), discovery)
    scheduler.start()
    await asyncio.wait_for(discovery.called.wait(), timeout=1)
    await asyncio.sleep(0)
    assert scheduler.running is True
    assert discovery.calls == 1
    discovery.called.clear()
    await asyncio.wait_for(discovery.called.wait(), timeout=1)
    assert discovery.calls >= 2
    assert scheduler.running is True
    await scheduler.stop()
    assert scheduler.running is False


class FlakyClientManager:
    def __init__(self) -> None:
        self.calls = 0

    async def configured(self) -> bool:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary database error")
        return True


class RecoveringDiscovery(FlakyDiscovery):
    def __init__(self) -> None:
        super().__init__()
        self.client_manager = FlakyClientManager()

    async def refresh(self, _trigger: str):
        self.calls += 1
        self.called.set()


@pytest.mark.asyncio
async def test_scheduler_retries_after_configuration_lookup_error() -> None:
    discovery = RecoveringDiscovery()
    scheduler = RefreshScheduler(FakeDatabase(), discovery)
    scheduler.start()
    await asyncio.wait_for(discovery.called.wait(), timeout=1)
    assert discovery.client_manager.calls >= 2
    assert scheduler.running is True
    await scheduler.stop()
