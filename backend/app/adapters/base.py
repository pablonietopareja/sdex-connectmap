from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urlsplit

from app.core.errors import SDEXParseError
from app.core.security import sanitize_text
from app.models.schemas import ConnectionNode, ConnectionStatus, ConnectionType

SENSITIVE_KEY_PARTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "nonce",
        "signature",
        "auth",
        "certificate",
        "privatekey",
        "keypassword",
        "username",
        "user",
    }
)
SAFE_METADATA_KEYS = frozenset(
    {
        "rack",
        "slot",
        "deviceid",
        "unitid",
        "protocol",
        "transport",
        "securitymode",
        "securitypolicy",
        "clientid",
        "keepalive",
        "qos",
        "cleanstart",
        "connectionstate",
        "connectionstatus",
        "plcconnectionstatus",
        "nckconnectionstatus",
        "plcenabled",
        "nckenabled",
        "producttype",
        "fqdn",
        "httpapi",
        "os",
        "arch",
        "demo",
        "allconnected",
        "status",
        "description",
        "model",
        "vendor",
        "networkadapter",
        "interface",
        "redundancy",
        "publishinginterval",
        "sessiontimeout",
    }
)


def normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def get_field(data: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    wanted = {normalized_key(name) for name in names}
    for key, value in data.items():
        if normalized_key(key) in wanted:
            return value
    return default


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on", "enabled", "licensed"}:
            return True
        if normalized in {"false", "0", "no", "off", "disabled", "unlicensed"}:
            return False
    return None


def parse_port(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 0 <= port <= 65535 else None


def normalize_status_value(value: Any) -> ConnectionStatus:
    if isinstance(value, bool):
        return ConnectionStatus.CONNECTED if value else ConnectionStatus.DISCONNECTED
    if value is None:
        return ConnectionStatus.UNKNOWN
    normalized = normalized_key(value)
    if normalized in {
        "connected",
        "online",
        "running",
        "active",
        "up",
        "ok",
        "ready",
        "established",
    }:
        return ConnectionStatus.CONNECTED
    if normalized in {
        "disconnected",
        "offline",
        "notconnected",
        "connectionlost",
        "down",
        "closed",
        "unreachable",
    }:
        return ConnectionStatus.DISCONNECTED
    if normalized in {"degraded", "fault", "faulted", "error", "warning", "partial"}:
        return ConnectionStatus.DEGRADED
    return ConnectionStatus.UNKNOWN


def stable_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug or "unnamed"


def _safe_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def safe_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in data.items():
        key_normalized = normalized_key(key)
        if any(part in key_normalized for part in SENSITIVE_KEY_PARTS):
            continue
        if key_normalized not in SAFE_METADATA_KEYS:
            continue
        if _safe_scalar(value):
            metadata[str(key)] = sanitize_text(value) if isinstance(value, str) else value
        elif (
            isinstance(value, list)
            and len(value) <= 20
            and all(_safe_scalar(item) for item in value)
        ):
            metadata[str(key)] = [
                sanitize_text(item) if isinstance(item, str) else item for item in value
            ]
    return metadata


def extract_endpoint_parts(endpoint_url: str | None) -> tuple[str | None, int | None]:
    if not endpoint_url:
        return None, None
    try:
        parsed = urlsplit(endpoint_url)
        return parsed.hostname, parsed.port
    except ValueError:
        return None, None


def _record_list_from_mapping(
    value: Mapping[str, Any],
    name_field: str,
) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for name, record in value.items():
        if not isinstance(record, Mapping):
            continue
        mutable = dict(record)
        if get_field(mutable, "name", "connectionName", "endpointName") is None:
            mutable[name_field] = str(name)
        records.append(mutable)
    return records


class BaseAdapter:
    endpoint: ClassVar[str]
    module_name: ClassVar[str]
    connection_type: ClassVar[ConnectionType]
    label: ClassVar[str]
    icon: ClassVar[str]
    subtype: ClassVar[str | None] = None
    container_keys: ClassVar[tuple[str, ...]] = (
        "connections",
        "items",
        "value",
        "data",
    )
    name_fields: ClassVar[tuple[str, ...]] = (
        "connectionName",
        "ConnectionName",
        "name",
        "Name",
        "endpointName",
        "EndpointName",
    )
    address_fields: ClassVar[tuple[str, ...]] = (
        "Address",
        "address",
        "ipAddress",
        "IPAddress",
        "hostname",
        "host",
    )
    port_fields: ClassVar[tuple[str, ...]] = (
        "Port",
        "port",
        "tcpPort",
        "TCPPort",
    )
    endpoint_fields: ClassVar[tuple[str, ...]] = (
        "endpoint-url",
        "endpointUrl",
        "EndpointUrl",
        "URL",
        "url",
        "brokerUrl",
    )
    enabled_fields: ClassVar[tuple[str, ...]] = ("Enabled", "enabled", "isEnabled")
    licensed_fields: ClassVar[tuple[str, ...]] = ("Licensed", "licensed", "isLicensed")
    status_fields: ClassVar[tuple[str, ...]] = (
        "ConnectionStatus",
        "connectionStatus",
        "status",
        "Status",
    )

    def extract_records(self, payload: Any) -> list[Mapping[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, list):
            if not all(isinstance(item, Mapping) for item in payload):
                raise SDEXParseError(f"{self.module_name} returned a non-object list item.")
            return list(payload)
        if not isinstance(payload, Mapping):
            raise SDEXParseError(f"{self.module_name} returned an unsupported JSON shape.")

        for container_key in self.container_keys:
            candidate = get_field(payload, container_key)
            if isinstance(candidate, list):
                if not all(isinstance(item, Mapping) for item in candidate):
                    raise SDEXParseError(
                        f"{self.module_name} returned a non-object connection item."
                    )
                return list(candidate)
            if isinstance(candidate, Mapping):
                return _record_list_from_mapping(candidate, self.name_fields[0])

        # Some versions return one connection object for collection routes.
        if any(get_field(payload, field) is not None for field in self.name_fields):
            return [payload]
        # Also tolerate a map keyed by connection name.
        mapped = _record_list_from_mapping(payload, self.name_fields[0])
        if mapped:
            return mapped
        if not payload:
            return []
        raise SDEXParseError(f"{self.module_name} response contains no connection collection.")

    def parse(
        self,
        payload: Any,
        *,
        observed_at: datetime | None = None,
        previous_nodes: Mapping[str, ConnectionNode] | None = None,
    ) -> list[ConnectionNode]:
        timestamp = observed_at or datetime.now(UTC)
        previous_nodes = previous_nodes or {}
        records = self.extract_records(payload)
        parsed = [
            (self.parse_record(record, index=index, observed_at=timestamp), record)
            for index, record in enumerate(records)
        ]
        grouped: dict[str, list[tuple[ConnectionNode, Mapping[str, Any]]]] = {}
        for node, record in parsed:
            grouped.setdefault(node.id, []).append((node, record))

        assigned: dict[int, str] = {}
        for base_id, group in grouped.items():
            previous_candidates = sorted(
                (
                    previous
                    for previous_id, previous in previous_nodes.items()
                    if previous_id == base_id or previous_id.startswith(f"{base_id}:")
                ),
                key=lambda previous: previous.id,
            )
            unused_previous = {previous.id: previous for previous in previous_candidates}

            # Exact endpoint/address matches preserve IDs when another same-name
            # connection disappears or the API changes collection ordering.
            for node, _record in group:
                node_identity = self._network_identity(node)
                matches = [
                    previous
                    for previous in unused_previous.values()
                    if self._network_identity(previous) == node_identity
                ]
                if len(matches) == 1 and any(node_identity):
                    match = matches[0]
                    assigned[id(node)] = match.id
                    unused_previous.pop(match.id, None)

            unassigned = [(node, record) for node, record in group if id(node) not in assigned]
            # A unique connection keeps its old name-based ID even if its network
            # address changes. With multiple changed peers, pair deterministically
            # with the remaining historical IDs rather than regenerating layout IDs.
            if unassigned and len(unassigned) == len(unused_previous):
                ordered_nodes = sorted(
                    unassigned,
                    key=lambda pair: self._identity_sort_key(pair[0], pair[1]),
                )
                for (node, _record), previous in zip(
                    ordered_nodes,
                    sorted(unused_previous.values(), key=lambda item: item.id),
                    strict=True,
                ):
                    assigned[id(node)] = previous.id
                unused_previous.clear()

            unassigned = [(node, record) for node, record in group if id(node) not in assigned]
            used_group_ids = {assigned[id(node)] for node, _record in group if id(node) in assigned}
            ordered_new = sorted(
                unassigned,
                key=lambda pair: self._identity_sort_key(pair[0], pair[1]),
            )
            for node, record in ordered_new:
                if base_id not in used_group_ids:
                    assigned[id(node)] = base_id
                    used_group_ids.add(base_id)
                    continue
                collision_data = {
                    "endpoint_url": node.endpoint_url,
                    "address": node.address,
                    "host": node.host,
                    "port": node.port,
                    "subtype": node.subtype,
                    "metadata": safe_metadata(record),
                }
                suffix = hashlib.sha256(
                    json.dumps(
                        collision_data,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:10]
                candidate = f"{base_id}:{suffix}"
                duplicate_index = 2
                while candidate in used_group_ids:
                    candidate = f"{base_id}:{suffix}-{duplicate_index}"
                    duplicate_index += 1
                assigned[id(node)] = candidate
                used_group_ids.add(candidate)

        result: list[ConnectionNode] = []
        for node, _record in parsed:
            candidate_id = assigned[id(node)]
            if candidate_id != node.id:
                node = node.model_copy(update={"id": candidate_id})
            previous = previous_nodes.get(candidate_id)
            if previous and previous.status == node.status:
                node = node.model_copy(
                    update={"last_status_change_at": previous.last_status_change_at}
                )
            result.append(node)
        return result

    @staticmethod
    def _network_identity(node: ConnectionNode) -> tuple[Any, ...]:
        return (
            node.endpoint_url,
            node.address,
            node.host,
            node.port,
            node.subtype,
        )

    @classmethod
    def _identity_sort_key(
        cls,
        node: ConnectionNode,
        record: Mapping[str, Any],
    ) -> str:
        return json.dumps(
            {
                "network": cls._network_identity(node),
                "metadata": safe_metadata(record),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def parse_record(
        self,
        record: Mapping[str, Any],
        *,
        index: int,
        observed_at: datetime,
    ) -> ConnectionNode:
        raw_name = get_field(record, *self.name_fields)
        display_name = (
            str(raw_name).strip()
            if raw_name is not None and str(raw_name).strip()
            else f"Unnamed {self.label} {index + 1}"
        )
        endpoint_value = get_field(record, *self.endpoint_fields)
        endpoint_url = str(endpoint_value).strip() if endpoint_value not in (None, "") else None
        address_value = get_field(record, *self.address_fields)
        address = str(address_value).strip() if address_value not in (None, "") else None
        explicit_host = get_field(record, "hostname", "host", "Host")
        endpoint_host, endpoint_port = extract_endpoint_parts(endpoint_url)
        host = (
            str(explicit_host).strip()
            if explicit_host not in (None, "")
            else endpoint_host or address
        )
        port = parse_port(get_field(record, *self.port_fields))
        if port is None:
            port = endpoint_port

        enabled_value = parse_bool(get_field(record, *self.enabled_fields))
        enabled = True if enabled_value is None else enabled_value
        licensed = parse_bool(get_field(record, *self.licensed_fields))
        raw_status = get_field(record, *self.status_fields)
        status, reason = self.determine_status(
            record,
            enabled=enabled,
            licensed=licensed,
            raw_status=raw_status,
        )
        node_id = f"{self.connection_type.value}:{stable_slug(display_name)}"
        return ConnectionNode(
            id=node_id,
            type=self.connection_type,
            subtype=self.subtype,
            display_name=display_name,
            address=address or endpoint_url,
            host=host,
            port=port,
            endpoint_url=endpoint_url,
            enabled=enabled,
            licensed=licensed,
            status=status,
            status_reason=reason,
            source_module=self.module_name,
            icon=self.icon,
            metadata=safe_metadata(record),
            last_seen_at=observed_at,
            last_status_change_at=observed_at,
            stale=False,
            capabilities=self.capabilities(record),
        )

    def determine_status(
        self,
        record: Mapping[str, Any],
        *,
        enabled: bool,
        licensed: bool | None,
        raw_status: Any,
    ) -> tuple[ConnectionStatus, str]:
        del record
        if not enabled:
            return ConnectionStatus.DISABLED, "Connection is disabled in SDEX."
        if licensed is False:
            return ConnectionStatus.UNLICENSED, "The required SDEX license is not active."
        status = normalize_status_value(raw_status)
        reasons = {
            ConnectionStatus.CONNECTED: "SDEX reports that the connection is established.",
            ConnectionStatus.DISCONNECTED: "SDEX reports that the connection is disconnected.",
            ConnectionStatus.DEGRADED: "SDEX reports a degraded or error state.",
            ConnectionStatus.UNKNOWN: "This module did not provide a recognized dynamic status.",
        }
        return status, reasons[status]

    def capabilities(self, record: Mapping[str, Any]) -> dict[str, Any]:
        del record
        return {}


def merge_previous_timestamp(
    nodes: Iterable[ConnectionNode],
    previous_nodes: Mapping[str, ConnectionNode],
) -> list[ConnectionNode]:
    result: list[ConnectionNode] = []
    for node in nodes:
        previous = previous_nodes.get(node.id)
        if previous and previous.status == node.status:
            node = node.model_copy(update={"last_status_change_at": previous.last_status_change_at})
        result.append(node)
    return result
