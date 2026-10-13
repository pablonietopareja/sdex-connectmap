from __future__ import annotations

import asyncio

import pytest

from app.services.events import EventBroker


@pytest.mark.asyncio
async def test_slow_subscriber_keeps_latest_notifications_with_bounded_queue() -> None:
    broker = EventBroker(queue_size=2)
    async with broker.subscribe() as queue:
        assert broker.subscriber_count == 1
        for sequence in range(4):
            await broker.publish({"type": "topology.updated", "sequence": sequence})
        assert queue.qsize() == 2
        assert (await queue.get())["sequence"] == 2
        assert (await queue.get())["sequence"] == 3
    assert broker.subscriber_count == 0


@pytest.mark.asyncio
async def test_cancelled_stream_releases_its_subscription() -> None:
    broker = EventBroker()
    connected = asyncio.Event()

    async def stream() -> None:
        async with broker.subscribe() as queue:
            connected.set()
            await queue.get()

    task = asyncio.create_task(stream())
    await asyncio.wait_for(connected.wait(), timeout=1)
    assert broker.subscriber_count == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert broker.subscriber_count == 0
