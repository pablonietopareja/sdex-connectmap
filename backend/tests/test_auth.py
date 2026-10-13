from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
import pytest

from app.core.errors import DefaultPasswordError, SDEXResponseError
from app.models.schemas import ConnectionProfile
from app.services.sdex_auth import (
    SDEXAuth,
    build_auth_header,
    compute_signature,
    generate_client_nonce,
)
from app.services.sdex_client import SDEXClient, TransientModuleError

CLIENT_NONCE = base64.b64encode(b"A" * 32).decode("ascii")
SERVER_NONCE = base64.b64encode(b"B" * 32).decode("ascii")
EXPECTED_SIGNATURE = "cmFrOb1kw4W9JnZStcY6wB5HMaB0zLdoKVlqpHd1EyM="
EXPECTED_HEADER = "User=admin;Signature=cmFrOb1kw4W9JnZStcY6wB5HMaB0zLdoKVlqpHd1EyM%3D"


def test_known_signature_vector() -> None:
    assert compute_signature(SERVER_NONCE, CLIENT_NONCE) == EXPECTED_SIGNATURE
    assert build_auth_header("admin", SERVER_NONCE, CLIENT_NONCE) == EXPECTED_HEADER


def test_username_is_url_encoded() -> None:
    header = build_auth_header("john doe+ops", SERVER_NONCE, CLIENT_NONCE)
    assert header.startswith("User=john%20doe%2Bops;Signature=")


def test_generated_nonce_is_cryptographically_sized_base64() -> None:
    assert len(base64.b64decode(generate_client_nonce(), validate=True)) == 32


@pytest.mark.asyncio
async def test_login_and_refresh_replace_both_nonces() -> None:
    new_client_nonce = base64.b64encode(b"C" * 32).decode()
    new_server_nonce = base64.b64encode(b"S" * 32).decode()
    nonces = iter((CLIENT_NONCE, new_client_nonce))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/by-password"):
            assert json.loads(request.content) == {
                "name": "admin",
                "password": "secret",
                "clientNonce": CLIENT_NONCE,
            }
            return httpx.Response(
                200,
                json={
                    "id": "session-1",
                    "serverNonce": SERVER_NONCE,
                    "expiryTime": 120,
                },
            )
        assert request.url.path.endswith("/refresh-token")
        assert request.headers["Auth"] == EXPECTED_HEADER
        assert json.loads(request.content) == {
            "oldServerNonce": SERVER_NONCE,
            "newClientNonce": new_client_nonce,
        }
        return httpx.Response(
            200,
            json={"newServerNonce": new_server_nonce, "expiryTime": 500},
        )

    async with httpx.AsyncClient(
        base_url="https://sdex.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        auth = SDEXAuth(
            client,
            "admin",
            "secret",
            nonce_factory=lambda: next(nonces),
            clock=lambda: 100,
            refresh_margin_seconds=30,
        )
        first = await auth.login()
        refreshed = await auth.ensure_authenticated()

    assert len(seen) == 2
    assert first.server_nonce == SERVER_NONCE
    assert refreshed.server_nonce == new_server_nonce
    assert refreshed.client_nonce == new_client_nonce
    assert refreshed.auth_header == build_auth_header("admin", new_server_nonce, new_client_nonce)
    assert refreshed.auth_header != first.auth_header


@pytest.mark.asyncio
async def test_refresh_expiry_relogs_in_exactly_once() -> None:
    server_two = base64.b64encode(b"2" * 32).decode()
    nonce_values = iter(
        (
            base64.b64encode(b"a" * 32).decode(),
            base64.b64encode(b"b" * 32).decode(),
            base64.b64encode(b"c" * 32).decode(),
        )
    )
    logins = 0
    refreshes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal logins, refreshes
        if request.url.path.endswith("/by-password"):
            logins += 1
            return httpx.Response(
                200,
                json={
                    "id": f"s{logins}",
                    "serverNonce": SERVER_NONCE if logins == 1 else server_two,
                    "expiryTime": 101 if logins == 1 else 500,
                },
            )
        refreshes += 1
        return httpx.Response(401, json={"Message": "expired"})

    async with httpx.AsyncClient(
        base_url="https://sdex.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        auth = SDEXAuth(
            client,
            "admin",
            "secret",
            nonce_factory=lambda: next(nonce_values),
            clock=lambda: 100,
        )
        await auth.login()
        session = await auth.ensure_authenticated()

    assert logins == 2
    assert refreshes == 1
    assert session.server_nonce == server_two


@pytest.mark.asyncio
async def test_default_password_406_has_specific_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(406, json={"Message": "default password"})

    async with httpx.AsyncClient(
        base_url="https://sdex.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        auth = SDEXAuth(client, "admin", "secret")
        with pytest.raises(DefaultPasswordError):
            await auth.login()


@pytest.mark.asyncio
async def test_logout_is_bounded_when_sdex_hangs(monkeypatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "serverNonce": SERVER_NONCE,
                "expiryTime": int(time.time()) + 3600,
            },
        )

    async with httpx.AsyncClient(
        base_url="https://sdex.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        auth = SDEXAuth(
            client,
            "admin",
            "secret",
            logout_timeout_seconds=0.05,
        )
        await auth.login()

        async def hanging_post(*_args, **_kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(auth, "_post", hanging_post)
        await asyncio.wait_for(auth.logout(), timeout=0.5)
        assert auth.session is None


@pytest.mark.asyncio
async def test_client_retries_transient_get_only() -> None:
    calls = {"system": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/by-password"):
            return httpx.Response(
                200,
                json={
                    "serverNonce": SERVER_NONCE,
                    "expiryTime": int(time.time()) + 3600,
                },
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(200, json={})
        calls["system"] += 1
        if calls["system"] == 1:
            return httpx.Response(503, json={"Message": "temporary"})
        return httpx.Response(200, json={"status": "running"})

    profile = ConnectionProfile(
        base_url="https://sdex.test",
        username="admin",
        password="secret",
        verify_tls=True,
        timeout_seconds=2,
    )
    async with httpx.AsyncClient(
        base_url=profile.base_url,
        transport=httpx.MockTransport(handler),
    ) as raw_client:
        client = SDEXClient(
            profile,
            client=raw_client,
            sleep=lambda _delay: _completed(),
        )
        assert await client.get_system() == {"status": "running"}
        await client.close()
    assert calls["system"] == 2


@pytest.mark.asyncio
async def test_client_caps_transient_retries_at_two() -> None:
    calls = {"system": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/by-password"):
            return httpx.Response(
                200,
                json={
                    "serverNonce": SERVER_NONCE,
                    "expiryTime": int(time.time()) + 3600,
                },
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(200, json={})
        calls["system"] += 1
        return httpx.Response(503, json={"Message": "temporary"})

    profile = ConnectionProfile(
        base_url="https://sdex.test",
        username="admin",
        password="secret",
    )
    async with httpx.AsyncClient(
        base_url=profile.base_url,
        transport=httpx.MockTransport(handler),
    ) as raw_client:
        client = SDEXClient(
            profile,
            client=raw_client,
            max_retries=99,
            sleep=lambda _delay: _completed(),
        )
        with pytest.raises(TransientModuleError):
            await client.get_system()
        await client.close()

    assert client.max_retries == 2
    assert calls["system"] == 3


@pytest.mark.parametrize("status_code", [500, 504])
@pytest.mark.asyncio
async def test_client_does_not_retry_unconfirmed_server_statuses(
    status_code: int,
) -> None:
    calls = {"system": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/by-password"):
            return httpx.Response(
                200,
                json={
                    "serverNonce": SERVER_NONCE,
                    "expiryTime": int(time.time()) + 3600,
                },
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(200, json={})
        calls["system"] += 1
        return httpx.Response(status_code, json={"Message": "server error"})

    profile = ConnectionProfile(
        base_url="https://sdex.test",
        username="admin",
        password="secret",
    )
    async with httpx.AsyncClient(
        base_url=profile.base_url,
        transport=httpx.MockTransport(handler),
    ) as raw_client:
        client = SDEXClient(
            profile,
            client=raw_client,
            sleep=lambda _delay: _completed(),
        )
        with pytest.raises(SDEXResponseError):
            await client.get_system()
        await client.close()

    assert calls["system"] == 1


async def _completed() -> None:
    return None
