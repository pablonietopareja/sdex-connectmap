from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import math
import random
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography import x509
from cryptography.x509.oid import ExtensionOID

from app.adapters import default_adapters
from app.adapters.base import BaseAdapter, normalized_key, safe_metadata
from app.core.config import normalize_base_url
from app.core.errors import (
    AuthenticationError,
    DefaultPasswordError,
    PermissionDeniedError,
    SDEXResponseError,
    SDEXUnavailableError,
)
from app.models.schemas import ConnectionNode, NetworkInterfaceSource

from .networking import parse_network_interfaces
from .sdex_auth import SDEXAuth
from .sdex_client import NETWORK_INTERFACES_PATH, SYSTEM_PATH

MAX_TRANSIENT_RETRIES = 2
MAX_RESPONSE_BYTES = 512 * 1024
TRANSIENT_DIAGNOSTIC_STATUS_CODES = frozenset({502, 503})
OPCUA_INCOMING_CLIENTS_LIMITATION = (
    "OPC UA server discovery covers configured local endpoints only; "
    "SDEX API 3.01 does not expose active incoming client sessions."
)
_HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "SDEX-ConnectMap-Diagnostic/1.0",
}

TCPProbe = Callable[[str, int, float], Awaitable[None]]
TLSProbe = Callable[[str, int, ssl.SSLContext, float], Awaitable[bytes]]


class SDEXDiagnosticError(RuntimeError):
    """A safe, stage-specific failure suitable for direct CLI display."""

    def __init__(self, stage: str, code: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code


@dataclass(frozen=True, slots=True)
class DiagnosticTarget:
    base_url: str
    scheme: str
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class DiagnosticStep:
    ok: bool
    code: str
    message: str
    status_code: int | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
        }
        if self.status_code is not None:
            result["status_code"] = self.status_code
        return result


@dataclass(frozen=True, slots=True)
class CertificateSummary:
    sha256_fingerprint: str
    subject: str | None = None
    issuer: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    subject_alt_names: tuple[str, ...] = ()

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "sha256_fingerprint": self.sha256_fingerprint,
            "subject": self.subject,
            "issuer": self.issuer,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "subject_alt_names": list(self.subject_alt_names),
        }


@dataclass(frozen=True, slots=True)
class TLSDiagnostic:
    step: DiagnosticStep
    verified: bool | None
    fallback_used: bool
    certificate: CertificateSummary | None = None
    verification_error_code: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        result = self.step.to_safe_dict()
        result.update(
            {
                "verified": self.verified,
                "fallback_used": self.fallback_used,
                "certificate": (
                    self.certificate.to_safe_dict() if self.certificate is not None else None
                ),
            }
        )
        if self.verification_error_code is not None:
            result["verification_error_code"] = self.verification_error_code
        return result


@dataclass(frozen=True, slots=True)
class SystemSummary:
    product_type: str | None = None
    api_version: str | None = None
    status: str | None = None
    fqdn: str | None = None
    http_api: str | int | float | bool | None = None
    os: str | None = None
    arch: str | None = None
    demo: bool | None = None
    all_connected: bool | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "product_type": self.product_type,
            "api_version": self.api_version,
            "status": self.status,
            "fqdn": self.fqdn,
            "http_api": self.http_api,
            "os": self.os,
            "arch": self.arch,
            "demo": self.demo,
            "all_connected": self.all_connected,
        }


@dataclass(frozen=True, slots=True)
class EndpointDiagnostic:
    step: DiagnosticStep
    system: SystemSummary | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        result = self.step.to_safe_dict()
        if self.system is not None:
            result["system"] = self.system.to_safe_dict()
        return result


@dataclass(frozen=True, slots=True)
class NetworkAddressSummary:
    address: str
    prefix_length: int | None
    version: int

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "prefix_length": self.prefix_length,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class NetworkInterfaceSummary:
    name: str
    addresses: tuple[NetworkAddressSummary, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "addresses": [address.to_safe_dict() for address in self.addresses],
        }


@dataclass(frozen=True, slots=True)
class NetworkInterfacesDiagnostic:
    step: DiagnosticStep
    interfaces: tuple[NetworkInterfaceSummary, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        result = self.step.to_safe_dict()
        result["interfaces"] = [interface.to_safe_dict() for interface in self.interfaces]
        result["recognized_count"] = len(self.interfaces)
        return result


@dataclass(frozen=True, slots=True)
class ConnectionSummary:
    id: str
    display_name: str
    type: str
    subtype: str | None
    address: str | None
    port: int | None
    enabled: bool
    licensed: bool | None
    status: str
    source_module: str
    metadata: dict[str, Any]

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "type": self.type,
            "subtype": self.subtype,
            "address": self.address,
            "port": self.port,
            "enabled": self.enabled,
            "licensed": self.licensed,
            "status": self.status,
            "source_module": self.source_module,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ModuleConnectionsDiagnostic:
    module: str
    label: str
    type: str
    endpoint: str
    outcome: str
    count: int
    connections: tuple[ConnectionSummary, ...] = ()

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "label": self.label,
            "type": self.type,
            "endpoint": self.endpoint,
            "outcome": self.outcome,
            "count": self.count,
            "connections": [connection.to_safe_dict() for connection in self.connections],
        }


@dataclass(frozen=True, slots=True)
class ConnectionsDiagnostic:
    requested: bool
    complete: bool
    stopped_reason: str | None
    limitations: tuple[str, ...]
    modules: tuple[ModuleConnectionsDiagnostic, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "complete": self.complete,
            "stopped_reason": self.stopped_reason,
            "limitations": list(self.limitations),
            "modules": [module.to_safe_dict() for module in self.modules],
        }


@dataclass(frozen=True, slots=True)
class SDEXDiagnosticReport:
    target: DiagnosticTarget
    tcp: DiagnosticStep
    tls: TLSDiagnostic
    unauthenticated_system: EndpointDiagnostic
    authentication: DiagnosticStep
    system: SystemSummary
    network_interfaces: NetworkInterfacesDiagnostic
    connections: ConnectionsDiagnostic
    logout: DiagnosticStep

    def to_safe_dict(self) -> dict[str, Any]:
        """Return only explicitly reviewed fields, never credentials or raw payloads."""

        return {
            "base_url": self.target.base_url,
            "host": self.target.host,
            "port": self.target.port,
            "tcp": self.tcp.to_safe_dict(),
            "tls": self.tls.to_safe_dict(),
            "unauthenticated_system": self.unauthenticated_system.to_safe_dict(),
            "authentication": self.authentication.to_safe_dict(),
            "system": self.system.to_safe_dict(),
            "network_interfaces": self.network_interfaces.to_safe_dict(),
            "connections": self.connections.to_safe_dict(),
            "logout": self.logout.to_safe_dict(),
        }


def parse_diagnostic_target(base_url: str) -> DiagnosticTarget:
    if not isinstance(base_url, str):
        raise SDEXDiagnosticError("configuration", "invalid_base_url", "SDEX base URL is invalid.")
    candidate = base_url.strip()
    try:
        normalize_base_url(candidate)
        parsed = urlsplit(candidate)
        parsed_port = parsed.port
    except ValueError as exc:
        raise SDEXDiagnosticError(
            "configuration",
            "invalid_base_url",
            "SDEX base URL must be an exact HTTP or HTTPS origin without credentials or a path.",
        ) from exc
    if parsed.hostname is None:
        raise SDEXDiagnosticError("configuration", "invalid_base_url", "SDEX host is missing.")
    scheme = parsed.scheme.casefold()
    port = parsed_port if parsed_port is not None else (443 if scheme == "https" else 80)
    return DiagnosticTarget(
        base_url=candidate.rstrip("/"),
        scheme=scheme,
        host=parsed.hostname,
        port=port,
    )


async def _close_writer(writer: Any) -> None:
    writer.close()
    wait_closed = getattr(writer, "wait_closed", None)
    if wait_closed is None:
        return
    try:
        result = wait_closed()
        if inspect.isawaitable(result):
            await result
    except OSError:
        pass


async def _default_tcp_probe(host: str, port: int, timeout_seconds: float) -> None:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=timeout_seconds,
    )
    del reader
    await _close_writer(writer)


async def _default_tls_probe(
    host: str,
    port: int,
    context: ssl.SSLContext,
    timeout_seconds: float,
) -> bytes:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            host,
            port,
            ssl=context,
            server_hostname=host,
        ),
        timeout=timeout_seconds,
    )
    del reader
    try:
        ssl_object = writer.get_extra_info("ssl_object")
        certificate = ssl_object.getpeercert(binary_form=True) if ssl_object else None
        if not isinstance(certificate, bytes) or not certificate:
            raise SDEXDiagnosticError(
                "tls",
                "tls_certificate_missing",
                "The TLS peer did not provide a certificate.",
            )
        return certificate
    finally:
        await _close_writer(writer)


def _certificate_error(exc: ssl.SSLCertVerificationError) -> SDEXDiagnosticError:
    detail = f"{getattr(exc, 'verify_message', '')} {exc}".casefold()
    if "hostname" in detail or "ip address mismatch" in detail or "not valid for" in detail:
        code = "tls_hostname_mismatch"
        message = "The SDEX certificate is not valid for the configured host."
    elif "expired" in detail:
        code = "tls_certificate_expired"
        message = "The SDEX certificate has expired."
    elif "not yet valid" in detail:
        code = "tls_certificate_not_yet_valid"
        message = "The SDEX certificate is not valid yet."
    elif "self-signed" in detail:
        code = "tls_certificate_self_signed"
        message = "The SDEX certificate is self-signed and is not trusted."
    else:
        code = "tls_certificate_untrusted"
        message = "The SDEX certificate could not be verified with the configured trust store."
    return SDEXDiagnosticError("tls", code, message)


def _safe_certificate_text(value: object) -> str | None:
    text = "".join(character for character in str(value) if character.isprintable()).strip()
    return text[:512] or None


def _certificate_summary(der_certificate: bytes) -> CertificateSummary:
    digest = hashlib.sha256(der_certificate).hexdigest().upper()
    fingerprint = ":".join(digest[index : index + 2] for index in range(0, len(digest), 2))
    try:
        certificate = x509.load_der_x509_certificate(der_certificate)
    except ValueError:
        return CertificateSummary(sha256_fingerprint=fingerprint)

    subject_alt_names: list[str] = []
    try:
        extension = certificate.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value
        subject_alt_names.extend(extension.get_values_for_type(x509.DNSName))
        subject_alt_names.extend(
            str(value) for value in extension.get_values_for_type(x509.IPAddress)
        )
    except x509.ExtensionNotFound:
        pass
    safe_alt_names = tuple(
        value
        for value in (_safe_certificate_text(name) for name in subject_alt_names[:20])
        if value is not None
    )
    return CertificateSummary(
        sha256_fingerprint=fingerprint,
        subject=_safe_certificate_text(certificate.subject.rfc4514_string()),
        issuer=_safe_certificate_text(certificate.issuer.rfc4514_string()),
        valid_from=certificate.not_valid_before_utc.astimezone(UTC).isoformat(),
        valid_until=certificate.not_valid_after_utc.astimezone(UTC).isoformat(),
        subject_alt_names=safe_alt_names,
    )


def _verified_context(ca_cert_path: str | Path | None) -> ssl.SSLContext:
    try:
        if ca_cert_path is None:
            return ssl.create_default_context()
        path = Path(ca_cert_path).expanduser()
        if not path.is_file():
            raise OSError
        return ssl.create_default_context(cafile=str(path))
    except (OSError, ssl.SSLError) as exc:
        raise SDEXDiagnosticError(
            "tls",
            "tls_ca_file_invalid",
            "The configured CA certificate file could not be loaded.",
        ) from exc


def _unverified_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def _run_tcp_probe(
    target: DiagnosticTarget,
    timeout_seconds: float,
    probe: TCPProbe,
) -> DiagnosticStep:
    try:
        await probe(target.host, target.port, timeout_seconds)
    except TimeoutError as exc:
        raise SDEXDiagnosticError(
            "tcp",
            "tcp_timeout",
            "The TCP connection to SDEX timed out.",
        ) from exc
    except ConnectionRefusedError as exc:
        raise SDEXDiagnosticError(
            "tcp",
            "tcp_connection_refused",
            "The SDEX host refused the configured TCP port.",
        ) from exc
    except OSError as exc:
        raise SDEXDiagnosticError(
            "tcp",
            "tcp_unreachable",
            "The configured SDEX host or TCP port is unreachable.",
        ) from exc
    return DiagnosticStep(True, "tcp_connected", "The configured SDEX TCP endpoint is reachable.")


async def _run_tls_probe(
    target: DiagnosticTarget,
    timeout_seconds: float,
    ca_cert_path: str | Path | None,
    allow_unverified_tls: bool,
    probe: TLSProbe,
) -> tuple[TLSDiagnostic, ssl.SSLContext | bool]:
    if target.scheme != "https":
        if ca_cert_path is not None or allow_unverified_tls:
            raise SDEXDiagnosticError(
                "configuration",
                "tls_option_requires_https",
                "CA certificates and unverified TLS fallback require an HTTPS base URL.",
            )
        return (
            TLSDiagnostic(
                step=DiagnosticStep(
                    True, "tls_not_applicable", "The configured SDEX URL uses HTTP."
                ),
                verified=None,
                fallback_used=False,
            ),
            True,
        )

    verified_context = _verified_context(ca_cert_path)
    try:
        der_certificate = await probe(
            target.host,
            target.port,
            verified_context,
            timeout_seconds,
        )
    except ssl.SSLCertVerificationError as exc:
        verification_error = _certificate_error(exc)
        if not allow_unverified_tls:
            raise verification_error from exc
        unverified_context = _unverified_context()
        try:
            der_certificate = await probe(
                target.host,
                target.port,
                unverified_context,
                timeout_seconds,
            )
        except TimeoutError as fallback_exc:
            raise SDEXDiagnosticError(
                "tls",
                "tls_timeout",
                "The unverified laboratory TLS fallback timed out.",
            ) from fallback_exc
        except (ssl.SSLError, OSError) as fallback_exc:
            raise SDEXDiagnosticError(
                "tls",
                "tls_handshake_failed",
                "The unverified laboratory TLS fallback could not complete a handshake.",
            ) from fallback_exc
        return (
            TLSDiagnostic(
                step=DiagnosticStep(
                    True,
                    "tls_unverified_fallback",
                    "TLS completed only with the explicitly authorized unverified lab fallback.",
                ),
                verified=False,
                fallback_used=True,
                certificate=_certificate_summary(der_certificate),
                verification_error_code=verification_error.code,
            ),
            unverified_context,
        )
    except TimeoutError as exc:
        raise SDEXDiagnosticError(
            "tls",
            "tls_timeout",
            "The TLS handshake with SDEX timed out.",
        ) from exc
    except ssl.SSLError as exc:
        raise SDEXDiagnosticError(
            "tls",
            "tls_handshake_failed",
            "SDEX did not complete a valid TLS handshake.",
        ) from exc
    except OSError as exc:
        raise SDEXDiagnosticError(
            "tls",
            "tls_unreachable",
            "The TLS endpoint became unreachable.",
        ) from exc
    return (
        TLSDiagnostic(
            step=DiagnosticStep(True, "tls_verified", "The SDEX TLS certificate was verified."),
            verified=True,
            fallback_used=False,
            certificate=_certificate_summary(der_certificate),
        ),
        verified_context,
    )


def _normalized_key(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _field(payload: Mapping[str, Any], *names: str) -> Any:
    wanted = {_normalized_key(name) for name in names}
    for key, value in payload.items():
        if _normalized_key(key) in wanted:
            return value
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _safe_certificate_text(value)


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _system_summary(payload: Mapping[str, Any]) -> SystemSummary:
    http_api = _field(payload, "httpAPI", "HttpAPI")
    if not isinstance(http_api, str | int | float | bool):
        http_api = None
    return SystemSummary(
        product_type=_optional_text(_field(payload, "productType", "product", "ProductType")),
        api_version=_optional_text(_field(payload, "apiVersion", "version", "Version", "httpAPI")),
        status=_optional_text(_field(payload, "status", "Status")),
        fqdn=_optional_text(_field(payload, "fqdn", "FQDN")),
        http_api=http_api,
        os=_optional_text(_field(payload, "OS", "os", "operatingSystem")),
        arch=_optional_text(_field(payload, "arch", "architecture")),
        demo=_optional_bool(_field(payload, "demo", "Demo")),
        all_connected=_optional_bool(_field(payload, "allConnected", "AllConnected")),
    )


def _json_value(response: httpx.Response, stage: str) -> Any:
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise SDEXDiagnosticError(
            stage,
            "response_too_large",
            "SDEX returned a response larger than the diagnostic safety limit.",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SDEXDiagnosticError(
            stage,
            "invalid_json",
            "SDEX returned invalid JSON.",
        ) from exc
    return payload


def _json_mapping(response: httpx.Response, stage: str) -> Mapping[str, Any]:
    payload = _json_value(response, stage)
    if not isinstance(payload, Mapping):
        raise SDEXDiagnosticError(
            stage,
            "unexpected_json_shape",
            "SDEX returned an unexpected JSON shape.",
        )
    return payload


async def _get_with_retries(
    client: httpx.AsyncClient,
    path: str,
    *,
    stage: str,
    headers: Mapping[str, str] | None,
    max_transient_retries: int,
    sleep: Callable[[float], Awaitable[None]],
    random_source: Callable[[], float],
) -> httpx.Response:
    async def retry_delay(attempt: int) -> None:
        jitter = max(0.0, min(float(random_source()), 1.0)) * 0.05
        await sleep(0.1 * (2**attempt) + jitter)

    for attempt in range(max_transient_retries + 1):
        try:
            response = await client.get(path, headers=headers)
        except httpx.TimeoutException as exc:
            if attempt < max_transient_retries:
                await retry_delay(attempt)
                continue
            raise SDEXDiagnosticError(
                stage,
                "http_timeout",
                "The SDEX HTTP request timed out.",
            ) from exc
        except (httpx.NetworkError, httpx.ProtocolError) as exc:
            raise SDEXDiagnosticError(
                stage,
                "http_transport_error",
                "The SDEX HTTP request failed at the transport layer.",
            ) from exc
        if (
            response.status_code in TRANSIENT_DIAGNOSTIC_STATUS_CODES
            and attempt < max_transient_retries
        ):
            await retry_delay(attempt)
            continue
        return response
    raise AssertionError("bounded diagnostic retry loop did not return")


def _raise_authenticated_status(response: httpx.Response, stage: str) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise SDEXDiagnosticError(
            stage,
            "unexpected_redirect",
            "SDEX returned a redirect; confirm the exact base URL and port.",
        )
    if status == 401:
        raise SDEXDiagnosticError(
            stage,
            "authenticated_session_rejected",
            "SDEX rejected the newly authenticated session.",
        )
    if status == 403:
        raise SDEXDiagnosticError(
            stage,
            "permission_denied",
            "The SDEX user cannot read this endpoint.",
        )
    if status == 404:
        raise SDEXDiagnosticError(
            stage,
            "endpoint_not_available",
            "This SDEX endpoint is not available.",
        )
    if status == 406:
        raise SDEXDiagnosticError(
            stage,
            "default_password",
            "SDEX requires its default administrator password to be changed in SDEX.",
        )
    if status in TRANSIENT_DIAGNOSTIC_STATUS_CODES:
        raise SDEXDiagnosticError(
            stage,
            "transient_http_error",
            f"SDEX returned transient HTTP {status}.",
        )
    raise SDEXDiagnosticError(
        stage,
        "unexpected_http_status",
        f"SDEX returned unexpected HTTP {status}.",
    )


async def _unauthenticated_system_probe(
    client: httpx.AsyncClient,
    max_transient_retries: int,
    sleep: Callable[[float], Awaitable[None]],
    random_source: Callable[[], float],
) -> EndpointDiagnostic:
    response = await _get_with_retries(
        client,
        SYSTEM_PATH,
        stage="unauthenticated_system",
        headers=None,
        max_transient_retries=max_transient_retries,
        sleep=sleep,
        random_source=random_source,
    )
    status = response.status_code
    if 200 <= status < 300:
        return EndpointDiagnostic(
            step=DiagnosticStep(
                True,
                "unauthenticated_system_available",
                "The system endpoint is readable without authentication.",
                status,
            ),
            system=_system_summary(_json_mapping(response, "unauthenticated_system")),
        )
    if status in {401, 403, 406}:
        code = "unauthenticated_system_requires_authentication"
        if status == 406:
            code = "unauthenticated_system_default_password"
        return EndpointDiagnostic(
            step=DiagnosticStep(
                True,
                code,
                "The system endpoint is reachable but did not allow an unauthenticated read.",
                status,
            )
        )
    _raise_authenticated_status(response, "unauthenticated_system")
    raise AssertionError("unreachable status handling")


def _map_authentication_error(exc: Exception) -> SDEXDiagnosticError:
    if isinstance(exc, DefaultPasswordError):
        return SDEXDiagnosticError(
            "authentication",
            "default_password",
            "SDEX requires its default administrator password to be changed in SDEX.",
        )
    if isinstance(exc, AuthenticationError):
        return SDEXDiagnosticError(
            "authentication",
            "authentication_failed",
            "SDEX rejected the username or password.",
        )
    if isinstance(exc, PermissionDeniedError):
        return SDEXDiagnosticError(
            "authentication",
            "permission_denied",
            "The SDEX user is not permitted to authenticate.",
        )
    if isinstance(exc, SDEXUnavailableError):
        return SDEXDiagnosticError(
            "authentication",
            "authentication_endpoint_unavailable",
            "The SDEX authentication endpoint is unavailable.",
        )
    if isinstance(exc, SDEXResponseError):
        return SDEXDiagnosticError(
            "authentication",
            "unexpected_authentication_response",
            "SDEX returned an invalid authentication response.",
        )
    return SDEXDiagnosticError(
        "authentication",
        "authentication_failed",
        "SDEX authentication failed.",
    )


def _bounded_safe_text(value: object, *, limit: int = 512) -> str | None:
    text = "".join(character for character in str(value) if character.isprintable()).strip()
    return text[:limit] or None


def _safe_connection_address(node: ConnectionNode) -> str | None:
    candidate = _bounded_safe_text(node.host or node.address)
    if candidate is None:
        return None
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme and parsed.hostname:
            return _bounded_safe_text(parsed.hostname, limit=255)
    except ValueError:
        pass

    # A malformed or scheme-less URI must not smuggle userinfo or query values
    # through the otherwise allowlisted address field.
    candidate = candidate.rsplit("@", 1)[-1]
    candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    return _bounded_safe_text(candidate, limit=255)


def _safe_metadata_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _bounded_safe_text(value)
    if isinstance(value, list):
        sanitized = [_safe_metadata_value(item) for item in value[:20]]
        return [item for item in sanitized if item is not None]
    return None


def _diagnostic_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    # Re-apply the adapter metadata allowlist at the diagnostic boundary and
    # canonicalize keys so callers never receive arbitrary raw field names.
    filtered = safe_metadata(metadata)
    result: dict[str, Any] = {}
    for key in sorted(filtered, key=normalized_key):
        canonical_key = normalized_key(key)
        sanitized = _safe_metadata_value(filtered[key])
        if sanitized is not None:
            result[canonical_key] = sanitized
    return result


def _connection_summary(node: ConnectionNode) -> ConnectionSummary:
    return ConnectionSummary(
        id=_bounded_safe_text(node.id, limit=512) or "unknown",
        display_name=_bounded_safe_text(node.display_name) or "Unnamed connection",
        type=_bounded_safe_text(node.type, limit=100) or "unknown",
        subtype=_bounded_safe_text(node.subtype, limit=200) if node.subtype is not None else None,
        address=_safe_connection_address(node),
        port=node.port,
        enabled=node.enabled,
        licensed=node.licensed,
        status=_bounded_safe_text(node.status, limit=100) or "unknown",
        source_module=_bounded_safe_text(node.source_module, limit=100) or "unknown",
        metadata=_diagnostic_metadata(node.metadata),
    )


def _module_connections_result(
    adapter: BaseAdapter,
    outcome: str,
    connections: tuple[ConnectionSummary, ...] = (),
) -> ModuleConnectionsDiagnostic:
    return ModuleConnectionsDiagnostic(
        module=adapter.module_name,
        label=adapter.label,
        type=adapter.connection_type.value,
        endpoint=adapter.endpoint,
        outcome=outcome,
        count=len(connections),
        connections=connections,
    )


async def _probe_connections(
    client: httpx.AsyncClient,
    auth_header: str,
    max_transient_retries: int,
    sleep: Callable[[float], Awaitable[None]],
    random_source: Callable[[], float],
) -> ConnectionsDiagnostic:
    modules: list[ModuleConnectionsDiagnostic] = []
    for adapter in default_adapters():
        stage = f"connections:{adapter.module_name}"
        try:
            response = await _get_with_retries(
                client,
                adapter.endpoint,
                stage=stage,
                headers={"Auth": auth_header},
                max_transient_retries=max_transient_retries,
                sleep=sleep,
                random_source=random_source,
            )
        except SDEXDiagnosticError as exc:
            if exc.code not in {"http_timeout", "http_transport_error"}:
                raise
            modules.append(_module_connections_result(adapter, "transient"))
            continue

        status = response.status_code
        if status == 401:
            raise SDEXDiagnosticError(
                "connections",
                "authenticated_session_rejected",
                "SDEX rejected the authenticated session during connection discovery.",
            )
        if status == 406:
            modules.append(_module_connections_result(adapter, "default_password"))
            return ConnectionsDiagnostic(
                requested=True,
                complete=False,
                stopped_reason="default_password",
                limitations=(OPCUA_INCOMING_CLIENTS_LIMITATION,),
                modules=tuple(modules),
            )
        if status == 403:
            modules.append(_module_connections_result(adapter, "forbidden"))
            continue
        if status == 404:
            modules.append(_module_connections_result(adapter, "unavailable"))
            continue
        if status >= 500:
            modules.append(_module_connections_result(adapter, "transient"))
            continue
        if not 200 <= status < 300:
            modules.append(_module_connections_result(adapter, "unavailable"))
            continue

        try:
            payload = _json_value(response, stage)
            parsed = adapter.parse(payload)
            connections = tuple(_connection_summary(node) for node in parsed)
        except Exception:
            # Adapter/parser failures are isolated per module. Exception details
            # are intentionally omitted because they may contain raw SDEX data.
            modules.append(_module_connections_result(adapter, "parse"))
            continue
        modules.append(_module_connections_result(adapter, "ok", connections))

    return ConnectionsDiagnostic(
        requested=True,
        complete=True,
        stopped_reason=None,
        limitations=(OPCUA_INCOMING_CLIENTS_LIMITATION,),
        modules=tuple(modules),
    )


async def run_sdex_diagnostic(
    *,
    base_url: str,
    username: str,
    password: str,
    connect_timeout_seconds: float = 5,
    request_timeout_seconds: float = 15,
    ca_cert_path: str | Path | None = None,
    allow_unverified_tls: bool = False,
    include_connections: bool = False,
    max_transient_retries: int = 2,
    tcp_connector: TCPProbe | None = None,
    tls_connector: TLSProbe | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    random_source: Callable[[], float] = random.random,
) -> SDEXDiagnosticReport:
    """Run a bounded, read-only SDEX diagnostic without scheduler or persistence."""

    target = parse_diagnostic_target(base_url)
    if not username or not username.strip():
        raise SDEXDiagnosticError(
            "configuration",
            "username_required",
            "A SDEX username is required.",
        )
    if not password:
        raise SDEXDiagnosticError(
            "configuration",
            "password_required",
            "A SDEX password is required.",
        )
    if not isinstance(include_connections, bool):
        raise SDEXDiagnosticError(
            "configuration",
            "invalid_include_connections",
            "Connection discovery must be explicitly enabled or disabled.",
        )
    if (
        isinstance(connect_timeout_seconds, bool)
        or not isinstance(connect_timeout_seconds, int | float)
        or not 0.1 <= connect_timeout_seconds <= 120
    ):
        raise SDEXDiagnosticError(
            "configuration",
            "invalid_connect_timeout",
            "The connection timeout must be between 0.1 and 120 seconds.",
        )
    if (
        isinstance(request_timeout_seconds, bool)
        or not isinstance(request_timeout_seconds, int | float)
        or not 0.1 <= request_timeout_seconds <= 120
    ):
        raise SDEXDiagnosticError(
            "configuration",
            "invalid_request_timeout",
            "The HTTP request timeout must be between 0.1 and 120 seconds.",
        )
    if (
        isinstance(max_transient_retries, bool)
        or not isinstance(max_transient_retries, int)
        or not 0 <= max_transient_retries <= MAX_TRANSIENT_RETRIES
    ):
        raise SDEXDiagnosticError(
            "configuration",
            "invalid_retry_limit",
            f"Transient retries must be between 0 and {MAX_TRANSIENT_RETRIES}.",
        )

    tcp = await _run_tcp_probe(
        target,
        float(connect_timeout_seconds),
        tcp_connector or _default_tcp_probe,
    )
    tls, http_verify = await _run_tls_probe(
        target,
        float(connect_timeout_seconds),
        ca_cert_path,
        allow_unverified_tls,
        tls_connector or _default_tls_probe,
    )

    client = httpx.AsyncClient(
        base_url=target.base_url,
        timeout=httpx.Timeout(
            float(request_timeout_seconds),
            connect=float(connect_timeout_seconds),
        ),
        verify=http_verify,
        follow_redirects=False,
        trust_env=False,
        transport=http_transport,
        headers=_HTTP_HEADERS,
    )
    auth = SDEXAuth(client, username.strip(), password)
    logout = DiagnosticStep(
        True,
        "logout_not_needed",
        "No authenticated session was created.",
    )
    connections = ConnectionsDiagnostic(
        requested=False,
        complete=False,
        stopped_reason=None,
        limitations=(),
        modules=(),
    )
    try:
        unauthenticated_system = await _unauthenticated_system_probe(
            client,
            max_transient_retries,
            sleep,
            random_source,
        )
        try:
            session = await auth.login()
        except (
            AuthenticationError,
            DefaultPasswordError,
            PermissionDeniedError,
            SDEXResponseError,
            SDEXUnavailableError,
        ) as exc:
            raise _map_authentication_error(exc) from exc
        authentication = DiagnosticStep(
            True,
            "authenticated",
            "Nonce authentication completed successfully.",
        )

        system_response = await _get_with_retries(
            client,
            SYSTEM_PATH,
            stage="authenticated_system",
            headers={"Auth": session.auth_header},
            max_transient_retries=max_transient_retries,
            sleep=sleep,
            random_source=random_source,
        )
        _raise_authenticated_status(system_response, "authenticated_system")
        system = _system_summary(_json_mapping(system_response, "authenticated_system"))

        netif_response = await _get_with_retries(
            client,
            NETWORK_INTERFACES_PATH,
            stage="network_interfaces",
            headers={"Auth": session.auth_header},
            max_transient_retries=max_transient_retries,
            sleep=sleep,
            random_source=random_source,
        )
        _raise_authenticated_status(netif_response, "network_interfaces")
        netif_payload = _json_mapping(netif_response, "network_interfaces")
        parsed_interfaces = parse_network_interfaces(
            netif_payload,
            source=NetworkInterfaceSource.SDEX,
        )
        interfaces = tuple(
            NetworkInterfaceSummary(
                name=interface.name,
                addresses=tuple(
                    NetworkAddressSummary(
                        address=address.address,
                        prefix_length=address.prefix_length,
                        version=address.version or ipaddress.ip_address(address.address).version,
                    )
                    for address in interface.addresses
                ),
            )
            for interface in parsed_interfaces
        )
        network_interfaces = NetworkInterfacesDiagnostic(
            step=DiagnosticStep(
                True,
                (
                    "network_interfaces_recognized"
                    if interfaces
                    else "network_interfaces_unrecognized"
                ),
                (
                    "SDEX network-interface data was parsed into recognized interfaces."
                    if interfaces
                    else (
                        "The SDEX network-interface endpoint responded, but its fields "
                        "did not provide an unambiguous supported interface shape."
                    )
                ),
                netif_response.status_code,
            ),
            interfaces=interfaces,
        )
        if include_connections:
            connections = await _probe_connections(
                client,
                session.auth_header,
                max_transient_retries,
                sleep,
                random_source,
            )
    finally:
        had_session = auth.session is not None
        await auth.logout()
        if had_session:
            logout = DiagnosticStep(
                True,
                "logout_best_effort_completed",
                "Best-effort logout completed; remote acknowledgement is not asserted.",
            )
        await client.aclose()

    return SDEXDiagnosticReport(
        target=target,
        tcp=tcp,
        tls=tls,
        unauthenticated_system=unauthenticated_system,
        authentication=authentication,
        system=system,
        network_interfaces=network_interfaces,
        connections=connections,
        logout=logout,
    )
