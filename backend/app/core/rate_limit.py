from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from .errors import RateLimitError


class InMemoryRateLimiter:
    """Small per-process guard for expensive interactive endpoints."""

    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, *, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            if len(self._requests) > 2048:
                for existing_key, timestamps in list(self._requests.items()):
                    while timestamps and timestamps[0] <= cutoff:
                        timestamps.popleft()
                    if not timestamps:
                        self._requests.pop(existing_key, None)
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                raise RateLimitError()
            requests.append(now)
