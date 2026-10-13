from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import SDEXResponseError

MAX_RUNTIME_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_AUTH_RESPONSE_BYTES = 64 * 1024


async def bounded_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    max_bytes: int,
    **kwargs: Any,
) -> httpx.Response:
    """Read a decoded response within a fixed bound and always release its stream."""

    async with client.stream(method, path, **kwargs) as response:
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=16 * 1024):
            if len(body) + len(chunk) > max_bytes:
                raise SDEXResponseError("SDEX response exceeds the permitted size limit.")
            body.extend(chunk)
        # aiter_bytes has already decoded Content-Encoding. The returned response
        # contains plain bytes rather than an active connection to the gateway.
        headers = dict(response.headers)
        headers.pop("content-encoding", None)
        headers.pop("content-length", None)
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=bytes(body),
            request=response.request,
            extensions=response.extensions,
        )
