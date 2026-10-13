from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.core.errors import (
    AuthenticationError,
    DefaultPasswordError,
    PermissionDeniedError,
    SDEXResponseError,
    SDEXUnavailableError,
)

from .http_transport import MAX_AUTH_RESPONSE_BYTES, bounded_request

LOGIN_PATH = "/runtime/core/auth/by-password"
REFRESH_PATH = "/runtime/core/auth/refresh-token"
LOGOUT_PATH = "/runtime/core/auth/logout"


def generate_client_nonce(size: int = 32) -> str:
    return base64.b64encode(secrets.token_bytes(size)).decode("ascii")


def compute_signature(server_nonce: str, client_nonce: str) -> str:
    try:
        server_bytes = base64.b64decode(server_nonce, validate=True)
        client_bytes = base64.b64decode(client_nonce, validate=True)
    except (ValueError, TypeError) as exc:
        raise SDEXResponseError("SDEX returned an invalid authentication nonce.") from exc
    digest = hashlib.sha256(server_bytes + client_bytes).digest()
    return base64.b64encode(digest).decode("ascii")


def build_auth_header(username: str, server_nonce: str, client_nonce: str) -> str:
    signature = compute_signature(server_nonce, client_nonce)
    return f"User={quote(username, safe='')};Signature={quote(signature, safe='')}"


def _expiry_timestamp(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SDEXResponseError("SDEX returned an invalid authentication expiry time.") from exc
    if not math.isfinite(result) or result <= 0:
        raise SDEXResponseError("SDEX returned an invalid authentication expiry time.")
    # Tolerate implementations returning milliseconds while the Linux schema says seconds.
    if result > 10_000_000_000:
        result /= 1000
    return result


def _json_object(response: httpx.Response, operation: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SDEXResponseError(f"SDEX returned invalid JSON during {operation}.") from exc
    if not isinstance(payload, Mapping):
        raise SDEXResponseError(f"SDEX returned an invalid {operation} response.")
    return payload


def _raise_auth_status(response: httpx.Response, operation: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 406:
        raise DefaultPasswordError()
    if response.status_code in {400, 401}:
        raise AuthenticationError(f"SDEX rejected the {operation} request.")
    if response.status_code == 403:
        raise PermissionDeniedError()
    raise SDEXResponseError(f"SDEX returned HTTP {response.status_code} during {operation}.")


@dataclass(frozen=True, slots=True)
class AuthSession:
    session_id: str | None
    client_nonce: str
    server_nonce: str
    expiry_time: float
    auth_header: str


class SDEXAuth:
    def __init__(
        self,
        client: httpx.AsyncClient,
        username: str,
        password: str,
        *,
        refresh_margin_seconds: float = 30,
        logout_timeout_seconds: float = 2,
        nonce_factory: Callable[[], str] = generate_client_nonce,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._username = username
        self._password = password
        self._refresh_margin = max(1, refresh_margin_seconds)
        self._logout_timeout = max(0.1, logout_timeout_seconds)
        self._nonce_factory = nonce_factory
        self._clock = clock
        self._session: AuthSession | None = None
        self._lock = asyncio.Lock()

    @property
    def session(self) -> AuthSession | None:
        return self._session

    @property
    def header(self) -> str | None:
        return self._session.auth_header if self._session else None

    def invalidate(self) -> None:
        self._session = None

    async def _post(
        self,
        path: str,
        *,
        json: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            return await bounded_request(
                self._client,
                "POST",
                path,
                max_bytes=MAX_AUTH_RESPONSE_BYTES,
                json=json,
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
            raise SDEXUnavailableError("SDEX authentication endpoint is unavailable.") from exc

    async def _login_unlocked(self) -> AuthSession:
        client_nonce = self._nonce_factory()
        response = await self._post(
            LOGIN_PATH,
            json={
                "name": self._username,
                "password": self._password,
                "clientNonce": client_nonce,
            },
        )
        _raise_auth_status(response, "login")
        payload = _json_object(response, "login")
        server_nonce = payload.get("serverNonce")
        if not isinstance(server_nonce, str) or not server_nonce:
            raise SDEXResponseError("SDEX login response did not contain serverNonce.")
        session = AuthSession(
            session_id=str(payload["id"]) if payload.get("id") is not None else None,
            client_nonce=client_nonce,
            server_nonce=server_nonce,
            expiry_time=_expiry_timestamp(payload.get("expiryTime")),
            auth_header=build_auth_header(self._username, server_nonce, client_nonce),
        )
        self._session = session
        return session

    async def login(self) -> AuthSession:
        async with self._lock:
            return await self._login_unlocked()

    async def _refresh_unlocked(self) -> AuthSession:
        if self._session is None:
            return await self._login_unlocked()
        previous = self._session
        new_client_nonce = self._nonce_factory()
        response = await self._post(
            REFRESH_PATH,
            json={
                "oldServerNonce": previous.server_nonce,
                "newClientNonce": new_client_nonce,
            },
            headers={"Auth": previous.auth_header},
        )
        _raise_auth_status(response, "refresh")
        payload = _json_object(response, "refresh")
        new_server_nonce = payload.get("newServerNonce")
        if not isinstance(new_server_nonce, str) or not new_server_nonce:
            raise SDEXResponseError("SDEX refresh response did not contain newServerNonce.")
        session = AuthSession(
            session_id=previous.session_id,
            client_nonce=new_client_nonce,
            server_nonce=new_server_nonce,
            expiry_time=_expiry_timestamp(payload.get("expiryTime")),
            auth_header=build_auth_header(
                self._username,
                new_server_nonce,
                new_client_nonce,
            ),
        )
        # Replace every nonce-derived value atomically only after a successful refresh.
        self._session = session
        return session

    async def refresh(self) -> AuthSession:
        async with self._lock:
            try:
                return await self._refresh_unlocked()
            except AuthenticationError:
                self._session = None
                return await self._login_unlocked()

    async def ensure_authenticated(self) -> AuthSession:
        async with self._lock:
            if self._session is None:
                return await self._login_unlocked()
            if self._clock() >= self._session.expiry_time - self._refresh_margin:
                try:
                    return await self._refresh_unlocked()
                except AuthenticationError:
                    # Exactly one re-login attempt; failures propagate without recursion.
                    self._session = None
                    return await self._login_unlocked()
            return self._session

    async def force_relogin(self) -> AuthSession:
        async with self._lock:
            self._session = None
            return await self._login_unlocked()

    async def logout(self) -> None:
        async with self._lock:
            session = self._session
            self._session = None
            if session is None:
                return
            try:
                response = await asyncio.wait_for(
                    self._post(
                        LOGOUT_PATH,
                        headers={"Auth": session.auth_header},
                    ),
                    timeout=self._logout_timeout,
                )
                _raise_auth_status(response, "logout")
            except Exception:
                # Logout is deliberately best-effort during profile changes and shutdown.
                return
