from __future__ import annotations

import base64
import ipaddress
import json
import ssl
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.adapters import default_adapters
from app.services import sdex_diagnostics
from app.services.sdex_diagnostics import (
    SDEXDiagnosticError,
    parse_diagnostic_target,
    run_sdex_diagnostic,
)

CLIENT_NONCE = base64.b64encode(b"C" * 32).decode("ascii")
SERVER_NONCE = base64.b64encode(b"S" * 32).decode("ascii")


async def _tcp_ok(_host: str, _port: int, _timeout: float) -> None:
    return None


def _recording_sleep(delays: list[float]):
    async def sleep(delay: float) -> None:
        delays.append(delay)

    return sleep


def _certificate_der() -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sdex.test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("sdex.test"),
                    x509.IPAddress(ipaddress.ip_address("192.0.2.10")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.DER)


def _success_transport(
    seen: list[tuple[str, str, bool]],
    *,
    unauthenticated_status: int = 200,
    transient_once: set[str] | None = None,
    connection_handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> httpx.MockTransport:
    transient_once = set() if transient_once is None else transient_once
    transient_seen: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        has_auth = "Auth" in request.headers
        seen.append((request.method, request.url.path, has_auth))
        path = request.url.path
        stage_key = f"{request.method}:{path}:{has_auth}"
        if stage_key in transient_once and stage_key not in transient_seen:
            transient_seen.add(stage_key)
            return httpx.Response(503, json={"Message": "temporary"})
        if request.method == "GET" and path.endswith("/system") and not has_auth:
            if unauthenticated_status != 200:
                return httpx.Response(unauthenticated_status, json={"Message": "auth required"})
            return httpx.Response(
                200,
                json={
                    "productType": "SDEX Suite",
                    "httpAPI": "3.01",
                    "status": "running",
                    "fqdn": "sdex.test",
                    "OS": "Linux",
                    "arch": "amd64",
                    "demo": False,
                    "allConnected": True,
                    "password": "must-not-escape",
                },
            )
        if path.endswith("/auth/by-password"):
            body = json.loads(request.content)
            assert body["name"] == "diagnostic-user"
            assert body["password"] == "diagnostic-password"
            assert "Auth" not in request.headers
            return httpx.Response(
                200,
                json={
                    "id": "session-id",
                    "serverNonce": SERVER_NONCE,
                    "expiryTime": int(time.time()) + 3600,
                },
            )
        if request.method == "GET" and path.endswith("/system") and has_auth:
            return httpx.Response(
                200,
                json={
                    "productType": "SDEX Suite",
                    "httpAPI": "3.01",
                    "status": "running",
                    "fqdn": "sdex.test",
                    "OS": "Linux",
                    "arch": "amd64",
                    "demo": False,
                    "allConnected": True,
                    "opaqueSecret": "must-not-escape",
                },
            )
        if path.endswith("/system/netif"):
            assert has_auth
            return httpx.Response(
                200,
                json={
                    "interfaces": [
                        {
                            "name": "eth1",
                            "address": "192.0.2.10",
                            "prefixLength": 24,
                            "proxySettings": {"password": "must-not-escape"},
                        }
                    ]
                },
            )
        if path.endswith("/auth/logout"):
            assert has_auth
            return httpx.Response(200)
        if connection_handler is not None:
            return connection_handler(request)
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    return httpx.MockTransport(handler)


def test_parse_target_keeps_the_confirmed_origin_and_rejects_paths() -> None:
    target = parse_diagnostic_target("https://192.0.2.10:1443")
    assert target.base_url == "https://192.0.2.10:1443"
    assert target.host == "192.0.2.10"
    assert target.port == 1443

    with pytest.raises(SDEXDiagnosticError) as captured:
        parse_diagnostic_target("https://192.0.2.10:1443/unconfirmed-path")
    assert captured.value.stage == "configuration"
    assert captured.value.code == "invalid_base_url"


@pytest.mark.asyncio
async def test_http_diagnostic_is_bounded_sanitized_and_disables_environment_proxies(
    monkeypatch,
) -> None:
    seen: list[tuple[str, str, bool]] = []
    tcp_timeouts: list[float] = []
    captured_client_options: dict[str, Any] = {}
    real_async_client = httpx.AsyncClient

    async def tcp_ok(_host: str, _port: int, timeout_value: float) -> None:
        tcp_timeouts.append(timeout_value)

    def client_factory(*args, **kwargs):
        captured_client_options.update(kwargs)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(sdex_diagnostics.httpx, "AsyncClient", client_factory)
    report = await run_sdex_diagnostic(
        base_url="http://192.0.2.10:8080",
        username="diagnostic-user",
        password="diagnostic-password",
        tcp_connector=tcp_ok,
        http_transport=_success_transport(seen),
    )

    safe = report.to_safe_dict()
    rendered = json.dumps(safe, sort_keys=True)
    assert safe["tcp"]["code"] == "tcp_connected"
    assert safe["tls"]["code"] == "tls_not_applicable"
    assert safe["authentication"]["code"] == "authenticated"
    assert safe["system"]["product_type"] == "SDEX Suite"
    assert safe["network_interfaces"]["interfaces"][0]["name"] == "eth1"
    assert safe["connections"] == {
        "requested": False,
        "complete": False,
        "stopped_reason": None,
        "limitations": [],
        "modules": [],
    }
    assert safe["logout"]["code"] == "logout_best_effort_completed"
    assert captured_client_options["trust_env"] is False
    assert captured_client_options["follow_redirects"] is False
    assert tcp_timeouts == [5.0]
    timeout = captured_client_options["timeout"]
    assert timeout.connect == 5.0
    assert timeout.read == 15.0
    assert timeout.write == 15.0
    assert timeout.pool == 15.0
    assert "diagnostic-password" not in rendered
    assert SERVER_NONCE not in rendered
    assert "must-not-escape" not in rendered
    assert sum(path.endswith("/auth/by-password") for _method, path, _auth in seen) == 1
    assert not any(path.endswith("/refresh-token") for _method, path, _auth in seen)
    adapter_paths = {adapter.endpoint for adapter in default_adapters()}
    assert not any(path in adapter_paths for _method, path, _auth in seen)


@pytest.mark.asyncio
async def test_https_verified_probe_returns_only_sanitized_certificate_metadata() -> None:
    seen: list[tuple[str, str, bool]] = []
    tls_contexts: list[ssl.SSLContext] = []
    certificate = _certificate_der()

    async def tls_ok(
        _host: str,
        _port: int,
        context: ssl.SSLContext,
        _timeout: float,
    ) -> bytes:
        tls_contexts.append(context)
        return certificate

    report = await run_sdex_diagnostic(
        base_url="https://192.0.2.10:1443",
        username="diagnostic-user",
        password="diagnostic-password",
        tcp_connector=_tcp_ok,
        tls_connector=tls_ok,
        http_transport=_success_transport(seen, unauthenticated_status=401),
    )

    safe_certificate = report.to_safe_dict()["tls"]["certificate"]
    assert report.tls.verified is True
    assert report.tls.fallback_used is False
    assert tls_contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert tls_contexts[0].check_hostname is True
    assert safe_certificate["subject"] == "CN=sdex.test"
    assert safe_certificate["issuer"] == "CN=sdex.test"
    assert safe_certificate["subject_alt_names"] == ["sdex.test", "192.0.2.10"]
    assert len(safe_certificate["sha256_fingerprint"].split(":")) == 32
    assert report.unauthenticated_system.step.status_code == 401


@pytest.mark.asyncio
async def test_tls_verification_failure_stops_without_explicit_fallback() -> None:
    calls = 0

    async def self_signed(
        _host: str,
        _port: int,
        _context: ssl.SSLContext,
        _timeout: float,
    ) -> bytes:
        nonlocal calls
        calls += 1
        raise ssl.SSLCertVerificationError(1, "self-signed certificate")

    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="https://192.0.2.10:1443",
            username="diagnostic-user",
            password="diagnostic-password",
            tcp_connector=_tcp_ok,
            tls_connector=self_signed,
            http_transport=httpx.MockTransport(
                lambda _request: pytest.fail("HTTP must not run after verified TLS failure")
            ),
        )

    assert captured.value.stage == "tls"
    assert captured.value.code == "tls_certificate_self_signed"
    assert calls == 1


@pytest.mark.asyncio
async def test_unverified_tls_requires_a_verified_probe_and_explicit_authorization() -> None:
    tls_contexts: list[ssl.SSLContext] = []
    seen: list[tuple[str, str, bool]] = []
    certificate = _certificate_der()

    async def verified_then_fallback(
        _host: str,
        _port: int,
        context: ssl.SSLContext,
        _timeout: float,
    ) -> bytes:
        tls_contexts.append(context)
        if len(tls_contexts) == 1:
            raise ssl.SSLCertVerificationError(1, "self-signed certificate")
        return certificate

    report = await run_sdex_diagnostic(
        base_url="https://192.0.2.10:1443",
        username="diagnostic-user",
        password="diagnostic-password",
        allow_unverified_tls=True,
        tcp_connector=_tcp_ok,
        tls_connector=verified_then_fallback,
        http_transport=_success_transport(seen),
    )

    assert len(tls_contexts) == 2
    assert tls_contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert tls_contexts[1].verify_mode == ssl.CERT_NONE
    assert tls_contexts[1].check_hostname is False
    assert report.tls.verified is False
    assert report.tls.fallback_used is True
    assert report.tls.verification_error_code == "tls_certificate_self_signed"
    assert report.tls.step.code == "tls_unverified_fallback"


@pytest.mark.asyncio
async def test_tcp_failure_stops_before_tls_and_http() -> None:
    async def refused(_host: str, _port: int, _timeout: float) -> None:
        raise ConnectionRefusedError

    async def forbidden_tls(*_args) -> bytes:
        pytest.fail("TLS must not run after TCP failure")

    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="https://192.0.2.10:1443",
            username="diagnostic-user",
            password="diagnostic-password",
            tcp_connector=refused,
            tls_connector=forbidden_tls,
            http_transport=httpx.MockTransport(
                lambda _request: pytest.fail("HTTP must not run after TCP failure")
            ),
        )

    assert captured.value.stage == "tcp"
    assert captured.value.code == "tcp_connection_refused"


@pytest.mark.asyncio
async def test_authentication_failure_is_sanitized_and_not_retried() -> None:
    calls = {"login": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/system"):
            return httpx.Response(401, json={"Message": "authentication required"})
        if request.url.path.endswith("/auth/by-password"):
            calls["login"] += 1
            return httpx.Response(
                401,
                json={"Message": "diagnostic-password should not escape"},
            )
        raise AssertionError("No request is expected after failed authentication")

    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="http://192.0.2.10:8080",
            username="diagnostic-user",
            password="diagnostic-password",
            tcp_connector=_tcp_ok,
            http_transport=httpx.MockTransport(handler),
        )

    assert captured.value.stage == "authentication"
    assert captured.value.code == "authentication_failed"
    assert "diagnostic-password" not in str(captured.value)
    assert calls["login"] == 1


@pytest.mark.asyncio
async def test_transient_get_retries_are_limited_and_login_is_never_retried() -> None:
    seen: list[tuple[str, str, bool]] = []
    delays: list[float] = []
    transient = {
        "GET:/runtime/core/system:False",
        "GET:/runtime/core/system:True",
        "GET:/runtime/core/system/netif:True",
    }
    report = await run_sdex_diagnostic(
        base_url="http://192.0.2.10:8080",
        username="diagnostic-user",
        password="diagnostic-password",
        max_transient_retries=1,
        tcp_connector=_tcp_ok,
        http_transport=_success_transport(seen, transient_once=transient),
        sleep=_recording_sleep(delays),
        random_source=lambda: 0,
    )

    assert report.authentication.ok is True
    assert sum(path.endswith("/auth/by-password") for _method, path, _auth in seen) == 1
    assert sum(path.endswith("/system") and not auth for _method, path, auth in seen) == 2
    assert sum(path.endswith("/system") and auth for _method, path, auth in seen) == 2
    assert sum(path.endswith("/system/netif") for _method, path, _auth in seen) == 2
    assert delays == [0.1, 0.1, 0.1]


@pytest.mark.asyncio
async def test_timeout_retries_use_short_exponential_backoff() -> None:
    seen: list[tuple[str, str, bool]] = []
    delays: list[float] = []
    system_attempts = 0
    base_transport = _success_transport(seen)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal system_attempts
        if (
            request.method == "GET"
            and request.url.path.endswith("/system")
            and "Auth" not in request.headers
        ):
            system_attempts += 1
            if system_attempts <= 2:
                raise httpx.ReadTimeout("simulated timeout", request=request)
        return await base_transport.handle_async_request(request)

    jitter = iter((0.0, 1.0))
    report = await run_sdex_diagnostic(
        base_url="http://192.0.2.10:8080",
        username="diagnostic-user",
        password="diagnostic-password",
        tcp_connector=_tcp_ok,
        http_transport=httpx.MockTransport(handler),
        sleep=_recording_sleep(delays),
        random_source=lambda: next(jitter),
    )

    assert report.authentication.ok is True
    assert system_attempts == 3
    assert delays == [0.1, 0.25]
    assert sum(path.endswith("/auth/by-password") for _method, path, _auth in seen) == 1


@pytest.mark.asyncio
async def test_opt_in_connection_diagnostic_queries_all_adapters_and_never_exposes_secrets() -> (
    None
):
    seen: list[tuple[str, str, bool]] = []
    adapters = default_adapters()
    adapters_by_path = {adapter.endpoint: adapter for adapter in adapters}

    def connection_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "Auth" in request.headers
        adapter = adapters_by_path[request.url.path]
        record: dict[str, Any] = {
            "connectionName": f"{adapter.module_name} connection",
            "Address": "192.0.2.20",
            "Port": 102,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": "connected",
            "rack": 0,
            "password": "record-password",
            "serverNonce": "record-nonce",
            "Auth": "record-auth",
            "certificate": "record-certificate",
            "privateKey": "record-private-key",
            "proxySettings": {
                "username": "proxy-user",
                "password": "proxy-password",
            },
        }
        if adapter.module_name == "mqtt":
            record.update(
                {
                    "connectionName": "Factory broker",
                    "brokerUrl": (
                        "mqtt://uri-user:uri-password@broker.example:8883/mqtt"
                        "?token=query-secret#fragment-secret"
                    ),
                    "connectionState": "connected",
                    "clientId": "reviewed-client-id",
                }
            )
            record.pop("Address")
            record.pop("Port")
            record.pop("ConnectionStatus")
            record.pop("rack")
        return httpx.Response(200, json={"connections": [record]})

    report = await run_sdex_diagnostic(
        base_url="http://192.0.2.10:8080",
        username="diagnostic-user",
        password="diagnostic-password",
        include_connections=True,
        tcp_connector=_tcp_ok,
        http_transport=_success_transport(
            seen,
            connection_handler=connection_handler,
        ),
    )

    safe = report.to_safe_dict()
    connections = safe["connections"]
    assert connections["requested"] is True
    assert connections["complete"] is True
    assert connections["stopped_reason"] is None
    assert connections["limitations"] == [
        (
            "OPC UA server discovery covers configured local endpoints only; "
            "SDEX API 3.01 does not expose active incoming client sessions."
        )
    ]
    assert [module["module"] for module in connections["modules"]] == [
        adapter.module_name for adapter in adapters
    ]
    assert [module["endpoint"] for module in connections["modules"]] == [
        adapter.endpoint for adapter in adapters
    ]
    assert all(module["outcome"] == "ok" for module in connections["modules"])
    assert all(module["count"] == 1 for module in connections["modules"])
    assert any(module["module"] == "focas" for module in connections["modules"])

    mqtt_module = next(module for module in connections["modules"] if module["module"] == "mqtt")
    mqtt_connection = mqtt_module["connections"][0]
    assert mqtt_connection == {
        "id": "mqtt_broker:factory-broker",
        "display_name": "Factory broker",
        "type": "mqtt_broker",
        "subtype": "MQTT Broker",
        "address": "broker.example",
        "port": 8883,
        "enabled": True,
        "licensed": True,
        "status": "connected",
        "source_module": "mqtt",
        "metadata": {
            "clientid": "reviewed-client-id",
            "connectionstate": "connected",
        },
    }
    assert set(mqtt_connection) == {
        "id",
        "display_name",
        "type",
        "subtype",
        "address",
        "port",
        "enabled",
        "licensed",
        "status",
        "source_module",
        "metadata",
    }

    rendered = json.dumps(safe, sort_keys=True)
    for forbidden in (
        "diagnostic-password",
        SERVER_NONCE,
        "record-password",
        "record-nonce",
        "record-auth",
        "record-certificate",
        "record-private-key",
        "proxy-user",
        "proxy-password",
        "uri-user",
        "uri-password",
        "query-secret",
        "fragment-secret",
    ):
        assert forbidden not in rendered
    module_calls = [
        (path, has_auth)
        for method, path, has_auth in seen
        if method == "GET" and path in adapters_by_path
    ]
    assert module_calls == [(adapter.endpoint, True) for adapter in adapters]
    assert not any(path.endswith("/refresh-token") for _method, path, _auth in seen)


@pytest.mark.asyncio
async def test_connection_module_failures_are_isolated_and_retries_remain_bounded() -> None:
    seen: list[tuple[str, str, bool]] = []
    delays: list[float] = []
    adapters = default_adapters()
    paths = [adapter.endpoint for adapter in adapters]

    def connection_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        assert "Auth" in request.headers
        if path == paths[0]:
            return httpx.Response(404, json={"Message": "not installed"})
        if path == paths[1]:
            return httpx.Response(403, json={"Message": "forbidden"})
        if path == paths[2]:
            return httpx.Response(200, content=b"{not-json")
        if path == paths[3]:
            return httpx.Response(503, json={"Message": "temporary"})
        if path == paths[4]:
            return httpx.Response(500, json={"Message": "server error"})
        return httpx.Response(200, json={"connections": []})

    report = await run_sdex_diagnostic(
        base_url="http://192.0.2.10:8080",
        username="diagnostic-user",
        password="diagnostic-password",
        include_connections=True,
        tcp_connector=_tcp_ok,
        http_transport=_success_transport(
            seen,
            connection_handler=connection_handler,
        ),
        sleep=_recording_sleep(delays),
        random_source=lambda: 0,
    )

    connections = report.to_safe_dict()["connections"]
    assert connections["complete"] is True
    assert [module["outcome"] for module in connections["modules"]] == [
        "unavailable",
        "forbidden",
        "parse",
        "transient",
        "transient",
        "ok",
        "ok",
        "ok",
        "ok",
    ]
    assert all(module["count"] == 0 for module in connections["modules"])
    assert delays == [0.1, 0.2]
    module_paths = [path for _method, path, _auth in seen if path in set(paths)]
    assert module_paths == [
        paths[0],
        paths[1],
        paths[2],
        paths[3],
        paths[3],
        paths[3],
        *paths[4:],
    ]


@pytest.mark.asyncio
async def test_connection_discovery_401_stops_immediately_and_logs_out() -> None:
    seen: list[tuple[str, str, bool]] = []
    first_path = default_adapters()[0].endpoint

    def connection_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == first_path
        return httpx.Response(401, json={"Message": "session rejected"})

    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="http://192.0.2.10:8080",
            username="diagnostic-user",
            password="diagnostic-password",
            include_connections=True,
            tcp_connector=_tcp_ok,
            http_transport=_success_transport(
                seen,
                connection_handler=connection_handler,
            ),
        )

    assert captured.value.stage == "connections"
    assert captured.value.code == "authenticated_session_rejected"
    adapter_paths = {adapter.endpoint for adapter in default_adapters()}
    assert [path for _method, path, _auth in seen if path in adapter_paths] == [first_path]
    assert sum(path.endswith("/auth/by-password") for _method, path, _auth in seen) == 1
    assert sum(path.endswith("/auth/logout") for _method, path, _auth in seen) == 1


@pytest.mark.asyncio
async def test_connection_discovery_406_records_policy_outcome_and_stops_safely() -> None:
    seen: list[tuple[str, str, bool]] = []
    adapters = default_adapters()
    first_path = adapters[0].endpoint
    second_path = adapters[1].endpoint

    def connection_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == first_path:
            return httpx.Response(200, json={"connections": []})
        assert request.url.path == second_path
        return httpx.Response(406, json={"Message": "default password"})

    report = await run_sdex_diagnostic(
        base_url="http://192.0.2.10:8080",
        username="diagnostic-user",
        password="diagnostic-password",
        include_connections=True,
        tcp_connector=_tcp_ok,
        http_transport=_success_transport(
            seen,
            connection_handler=connection_handler,
        ),
    )

    connections = report.to_safe_dict()["connections"]
    assert connections["complete"] is False
    assert connections["stopped_reason"] == "default_password"
    assert [module["outcome"] for module in connections["modules"]] == [
        "ok",
        "default_password",
    ]
    adapter_paths = {adapter.endpoint for adapter in adapters}
    assert [path for _method, path, _auth in seen if path in adapter_paths] == [
        first_path,
        second_path,
    ]
    assert sum(path.endswith("/auth/logout") for _method, path, _auth in seen) == 1


@pytest.mark.parametrize("status_code", [502, 503])
@pytest.mark.asyncio
async def test_final_transient_status_has_no_extra_delay(status_code: int) -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"Message": "temporary"})

    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="http://192.0.2.10:8080",
            username="diagnostic-user",
            password="diagnostic-password",
            tcp_connector=_tcp_ok,
            http_transport=httpx.MockTransport(handler),
            sleep=_recording_sleep(delays),
            random_source=lambda: 0,
        )

    assert captured.value.stage == "unauthenticated_system"
    assert captured.value.code == "transient_http_error"
    assert calls == 3
    assert delays == [0.1, 0.2]


@pytest.mark.parametrize("status_code", [500, 504])
@pytest.mark.asyncio
async def test_other_server_errors_are_not_retried(status_code: int) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"Message": "server error"})

    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="http://192.0.2.10:8080",
            username="diagnostic-user",
            password="diagnostic-password",
            tcp_connector=_tcp_ok,
            http_transport=httpx.MockTransport(handler),
            sleep=_recording_sleep(delays),
        )

    assert captured.value.code == "unexpected_http_status"
    assert calls == 1
    assert delays == []


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "authenticated_session_rejected"),
        (403, "permission_denied"),
        (406, "default_password"),
    ],
)
@pytest.mark.asyncio
async def test_authenticated_auth_errors_are_not_retried(
    status_code: int,
    expected_code: str,
) -> None:
    calls = {"login": 0, "authenticated_system": 0}
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "Auth" not in request.headers:
            return httpx.Response(401, json={"Message": "authentication required"})
        if request.url.path.endswith("/auth/by-password"):
            calls["login"] += 1
            return httpx.Response(
                200,
                json={
                    "serverNonce": SERVER_NONCE,
                    "expiryTime": int(time.time()) + 3600,
                },
            )
        if request.method == "GET" and request.url.path.endswith("/system"):
            calls["authenticated_system"] += 1
            return httpx.Response(status_code, json={"Message": "rejected"})
        if request.url.path.endswith("/auth/logout"):
            return httpx.Response(200)
        raise AssertionError("Unexpected diagnostic request")

    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="http://192.0.2.10:8080",
            username="diagnostic-user",
            password="diagnostic-password",
            tcp_connector=_tcp_ok,
            http_transport=httpx.MockTransport(handler),
            sleep=_recording_sleep(delays),
        )

    assert captured.value.code == expected_code
    assert calls == {"login": 1, "authenticated_system": 1}
    assert delays == []


@pytest.mark.asyncio
async def test_invalid_ca_path_is_a_clear_error(tmp_path) -> None:
    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="https://192.0.2.10:1443",
            username="diagnostic-user",
            password="diagnostic-password",
            ca_cert_path=tmp_path / "missing-ca.pem",
            tcp_connector=_tcp_ok,
        )
    assert captured.value.stage == "tls"
    assert captured.value.code == "tls_ca_file_invalid"


@pytest.mark.asyncio
async def test_configuration_never_accepts_unbounded_retries() -> None:
    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="http://192.0.2.10:8080",
            username="diagnostic-user",
            password="diagnostic-password",
            max_transient_retries=3,
            tcp_connector=_tcp_ok,
        )
    assert captured.value.code == "invalid_retry_limit"


@pytest.mark.asyncio
async def test_connection_discovery_opt_in_requires_an_explicit_boolean() -> None:
    with pytest.raises(SDEXDiagnosticError) as captured:
        await run_sdex_diagnostic(
            base_url="http://192.0.2.10:8080",
            username="diagnostic-user",
            password="diagnostic-password",
            include_connections=1,  # type: ignore[arg-type]
            tcp_connector=lambda *_args: pytest.fail("TCP must not run"),
        )
    assert captured.value.stage == "configuration"
    assert captured.value.code == "invalid_include_connections"
