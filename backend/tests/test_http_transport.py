from __future__ import annotations

import base64
import gzip
import time

import httpx
import pytest

from app.core.errors import SDEXResponseError
from app.models.schemas import ConnectionProfile
from app.services.http_transport import (
    MAX_AUTH_RESPONSE_BYTES,
    MAX_RUNTIME_RESPONSE_BYTES,
    bounded_request,
)
from app.services.sdex_auth import SDEXAuth
from app.services.sdex_client import SDEXClient


class RepeatedStream(httpx.AsyncByteStream):
    def __init__(self, chunk: bytes, count: int) -> None:
        self.chunk = chunk
        self.count = count
        self.consumed = 0
        self.closed = False

    async def __aiter__(self):
        for _ in range(self.count):
            self.consumed += len(self.chunk)
            yield self.chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_stream_limit_releases_connection_without_consuming_remainder() -> None:
    stream = RepeatedStream(b"x" * 16_384, 10)
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, stream=stream))
    async with httpx.AsyncClient(base_url="https://sdex.test", transport=transport) as client:
        with pytest.raises(SDEXResponseError, match="size limit"):
            await bounded_request(client, "GET", "/runtime/core/system", max_bytes=32_768)
    assert stream.closed
    assert stream.consumed == 49_152


@pytest.mark.asyncio
async def test_compressed_response_limit_counts_decoded_bytes() -> None:
    payload = b'{"message":"' + b"x" * 8192 + b'"}'
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=RepeatedStream(gzip.compress(payload), 1),
        )
    )
    async with httpx.AsyncClient(base_url="https://sdex.test", transport=transport) as client:
        with pytest.raises(SDEXResponseError, match="size limit"):
            await bounded_request(client, "GET", "/runtime/core/system", max_bytes=4096)


@pytest.mark.asyncio
async def test_decoded_response_preserves_json_and_status_at_limit() -> None:
    payload = b'{"status":"running"}'
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            stream=RepeatedStream(gzip.compress(payload), 1),
        )
    )
    async with httpx.AsyncClient(base_url="https://sdex.test", transport=transport) as client:
        response = await bounded_request(
            client, "GET", "/runtime/core/system", max_bytes=len(payload)
        )
    assert response.status_code == 200
    assert response.json() == {"status": "running"}
    assert "content-encoding" not in response.headers


@pytest.mark.asyncio
async def test_runtime_client_applies_its_limit_without_retrying_oversized_response() -> None:
    stream = RepeatedStream(b"x" * 16_384, MAX_RUNTIME_RESPONSE_BYTES // 16_384 + 8)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/by-password"):
            return httpx.Response(
                200,
                json={
                    "serverNonce": base64.b64encode(b"S" * 32).decode(),
                    "expiryTime": int(time.time()) + 3600,
                },
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(200, json={})
        return httpx.Response(200, stream=stream)

    profile = ConnectionProfile(
        base_url="https://sdex.test", username="reader", password="synthetic-password"
    )
    client = SDEXClient(profile, transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(SDEXResponseError, match="size limit"):
            await client.get_system()
    assert stream.closed
    assert stream.consumed == MAX_RUNTIME_RESPONSE_BYTES + 16_384
    assert seen.count("/runtime/core/system") == 1


@pytest.mark.asyncio
async def test_authentication_response_is_bounded() -> None:
    stream = RepeatedStream(b"x" * 16_384, 10)
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, stream=stream))
    async with httpx.AsyncClient(base_url="https://sdex.test", transport=transport) as client:
        auth = SDEXAuth(client, "reader", "synthetic-password")
        with pytest.raises(SDEXResponseError, match="size limit"):
            await auth.login()
        assert auth.session is None
    assert stream.closed
    assert stream.consumed == MAX_AUTH_RESPONSE_BYTES + 16_384


@pytest.mark.parametrize("expiry", ["nan", "inf", "-inf", 0, -1, 10**1000])
@pytest.mark.asyncio
async def test_authentication_rejects_nonfinite_or_nonpositive_expiry(expiry) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"serverNonce": base64.b64encode(b"S" * 32).decode(), "expiryTime": expiry},
        )
    )
    async with httpx.AsyncClient(base_url="https://sdex.test", transport=transport) as client:
        auth = SDEXAuth(client, "reader", "synthetic-password")
        with pytest.raises(SDEXResponseError, match="expiry time"):
            await auth.login()
        assert auth.session is None
