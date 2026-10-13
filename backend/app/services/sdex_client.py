from __future__ import annotations

import asyncio
import random
import ssl
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.errors import (
    AuthenticationError,
    DefaultPasswordError,
    PermissionDeniedError,
    SDEXParseError,
    SDEXResponseError,
    SDEXUnavailableError,
)
from app.models.schemas import ConnectionProfile

from .http_transport import MAX_RUNTIME_RESPONSE_BYTES, bounded_request
from .sdex_auth import SDEXAuth

SYSTEM_PATH = "/runtime/core/system"
NETWORK_INTERFACES_PATH = "/runtime/core/system/netif"
TRANSIENT_STATUS_CODES = frozenset({502, 503})


def _tls_verification(profile: ConnectionProfile) -> bool | ssl.SSLContext:
    if not profile.verify_tls:
        return False
    if profile.ca_cert_path is None:
        return True
    try:
        return ssl.create_default_context(cafile=str(profile.ca_cert_path))
    except (OSError, ssl.SSLError) as exc:
        raise ValueError("The configured SDEX CA certificate could not be loaded") from exc


class ModuleUnavailableError(SDEXResponseError):
    pass


class TransientModuleError(SDEXUnavailableError):
    pass


class SDEXClient:
    """Typed, read-only SDEX client plus the three authentication POSTs."""

    def __init__(
        self,
        profile: ConnectionProfile,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self.profile = profile
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=profile.base_url,
            timeout=httpx.Timeout(
                profile.timeout_seconds,
                connect=min(5.0, profile.timeout_seconds),
            ),
            verify=_tls_verification(profile),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
            headers={"Accept": "application/json", "User-Agent": "SDEX-ConnectMap/1.0"},
        )
        self.auth = SDEXAuth(
            self._client,
            profile.username,
            profile.password.get_secret_value(),
        )
        self.max_retries = min(max(0, max_retries), 2)
        self._sleep = sleep
        self._random = random_source
        self._closed = False

    async def login(self) -> None:
        await self.auth.login()

    async def _authorized_get(self, path: str) -> httpx.Response:
        session = await self.auth.ensure_authenticated()
        try:
            response = await bounded_request(
                self._client,
                "GET",
                path,
                max_bytes=MAX_RUNTIME_RESPONSE_BYTES,
                headers={"Auth": session.auth_header},
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
            raise TransientModuleError("SDEX request failed.") from exc
        if response.status_code == 401:
            # A server-side expiry can race the local clock. Retry once after re-login.
            session = await self.auth.force_relogin()
            try:
                response = await bounded_request(
                    self._client,
                    "GET",
                    path,
                    max_bytes=MAX_RUNTIME_RESPONSE_BYTES,
                    headers={"Auth": session.auth_header},
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
                raise TransientModuleError("SDEX request failed after re-login.") from exc
        return response

    @staticmethod
    def _raise_get_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 401:
            raise AuthenticationError()
        if status == 403:
            raise PermissionDeniedError()
        if status == 404:
            raise ModuleUnavailableError("This SDEX module endpoint is not available.")
        if status == 406:
            raise DefaultPasswordError()
        if status in TRANSIENT_STATUS_CODES:
            raise TransientModuleError(f"SDEX returned transient HTTP {status}.")
        raise SDEXResponseError(f"SDEX returned HTTP {status}.")

    async def get_json(self, path: str) -> Any:
        if not path.startswith("/runtime/"):
            raise ValueError("Only fixed SDEX runtime endpoints are permitted")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._authorized_get(path)
                self._raise_get_status(response)
                try:
                    return response.json()
                except ValueError as exc:
                    raise SDEXParseError("SDEX returned invalid JSON.") from exc
            except TransientModuleError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                delay = 0.2 * (2**attempt) + self._random() * 0.15
                await self._sleep(delay)
        raise TransientModuleError("SDEX request failed.") from last_error

    async def get_system(self) -> Any:
        return await self.get_json(SYSTEM_PATH)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.auth.logout()
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> SDEXClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()
