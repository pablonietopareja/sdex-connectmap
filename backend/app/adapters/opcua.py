import logging
from collections.abc import Mapping
from datetime import datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from app.models.schemas import ConnectionNode, ConnectionStatus, ConnectionType

from .base import BaseAdapter, get_field, parse_bool

logger = logging.getLogger(__name__)
_LOOPBACK_NAMES = frozenset({"localhost", "localhost."})


def _gateway_local_host(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    if "://" in candidate:
        try:
            candidate = urlsplit(candidate).hostname or ""
        except ValueError:
            return False
    candidate = candidate.strip().strip("[]").casefold()
    if candidate in _LOOPBACK_NAMES:
        return True
    try:
        return ip_address(candidate) in {ip_address("127.0.0.1"), ip_address("::1")}
    except ValueError:
        return False


def is_gateway_local_endpoint_record(record: Mapping[str, Any]) -> bool:
    """Classify only explicit loopback literals/names without DNS or probing."""

    candidates = (
        get_field(record, *BaseAdapter.address_fields),
        get_field(record, *BaseAdapter.endpoint_fields),
        get_field(record, "hostname", "host", "Host"),
    )
    return any(_gateway_local_host(candidate) for candidate in candidates)


class OpcUaClientAdapter(BaseAdapter):
    endpoint = "/runtime/opcua-client/connections"
    module_name = "opcua-client"
    connection_type = ConnectionType.OPCUA_REMOTE_SERVER
    label = "OPC UA Server"
    icon = "/icons/OPC_UA_Server.svg"
    subtype = "Remote OPC UA Server"
    container_keys = (
        "opcuaclientConnections",
        "opcuaClientConnections",
        *BaseAdapter.container_keys,
    )


class OpcUaServerAdapter(BaseAdapter):
    endpoint = "/runtime/opcua-server/endpoints"
    module_name = "opcua-server"
    connection_type = ConnectionType.OPCUA_LOCAL_ENDPOINT
    label = "OPC UA Endpoint"
    icon = "/icons/OPC_UA_Server.svg"
    subtype = "Local SDEX OPC UA Endpoint"
    container_keys = ("endpoints", "endpointSummaries", *BaseAdapter.container_keys)
    name_fields = ("endpointName", "name", "Name", "EndpointName")

    def parse_record(
        self,
        record: Mapping[str, Any],
        *,
        index: int,
        observed_at: datetime,
    ) -> ConnectionNode:
        node = super().parse_record(record, index=index, observed_at=observed_at)
        if not is_gateway_local_endpoint_record(record):
            return node
        explicit_binding = get_field(record, "interface", "interfaceName", "networkAdapter")
        single_external = isinstance(explicit_binding, str) and explicit_binding.strip() in {
            "eth1",
            "eth2",
        }
        capabilities = {
            **node.capabilities,
            "gateway_local": True,
            "external_interface_scope": ("single-external" if single_external else "all-external"),
            "active_incoming_session_telemetry": "unavailable",
        }
        logger.info(
            "Classified enabled OPC UA endpoint as a gateway-local service",
            extra={"event": "gateway_local_endpoint", "status": str(node.status)},
        )
        return node.model_copy(
            update={
                "local_service": True,
                "interface_scope": ("single-external" if single_external else "gateway-local"),
                "session_telemetry": "unavailable",
                "capabilities": capabilities,
            }
        )

    def determine_status(
        self,
        record: Mapping[str, Any],
        *,
        enabled: bool,
        licensed: bool | None,
        raw_status: Any,
    ) -> tuple[ConnectionStatus, str]:
        del raw_status
        if not enabled:
            return ConnectionStatus.DISABLED, "The local OPC UA endpoint is disabled."
        if licensed is False:
            return ConnectionStatus.UNLICENSED, "The required SDEX license is not active."
        access_protection = get_field(record, "accessProtection")
        if isinstance(access_protection, Mapping):
            endpoint_blocked = parse_bool(get_field(access_protection, "endpointStatus"))
            if endpoint_blocked is True:
                return (
                    ConnectionStatus.DEGRADED,
                    "OPC UA access protection currently disables this endpoint; "
                    "this is not a remote connection status.",
                )
        if is_gateway_local_endpoint_record(record):
            return (
                ConnectionStatus.CONNECTED,
                "Local SDEX endpoint is enabled and hosted by the gateway. "
                "SDEX API 3.01 does not expose active incoming OPC UA client sessions.",
            )
        return (
            ConnectionStatus.UNKNOWN,
            "The local endpoint is enabled; this does not imply a remote client session.",
        )
