from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.core.config import ALLOWED_REFRESH_INTERVALS, normalize_base_url
from app.core.security import public_endpoint


class ConnectionType(StrEnum):
    SDEX_GATEWAY = "sdex_gateway"
    SIEMENS_S7_1200_1500 = "siemens_s7_1200_1500"
    SIEMENS_S7_300_400 = "siemens_s7_300_400"
    ROCKWELL_ALLEN_BRADLEY = "rockwell_allen_bradley"
    MODBUS = "modbus"
    SINUMERIK_840D = "sinumerik_840d"
    FANUC_CNC = "fanuc_cnc"
    OPCUA_REMOTE_SERVER = "opcua_remote_server"
    OPCUA_LOCAL_ENDPOINT = "opcua_local_endpoint"
    MQTT_BROKER = "mqtt_broker"


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    DISABLED = "disabled"
    UNLICENSED = "unlicensed"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class VisualElementType(StrEnum):
    RACK = "rack"
    SWITCH = "switch"


class EdgeRoutingMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    ORTHOGONAL = "orthogonal"


class WaypointKind(StrEnum):
    FREE = "free"
    CORNER = "corner"


class ModuleStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    FORBIDDEN = "forbidden"
    DEFAULT_PASSWORD = "default_password"  # noqa: S105 - public status identifier
    TEMPORARY_ERROR = "temporary_error"
    PARSE_ERROR = "parse_error"
    AUTHENTICATION_ERROR = "authentication_error"


class AlarmSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Position(BaseModel):
    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def finite_coordinate(cls, value: float) -> float:
        if not math.isfinite(value) or abs(value) > 1_000_000:
            raise ValueError("coordinate is outside the supported range")
        return value


class Viewport(Position):
    zoom: float = Field(ge=0.05, le=8.0)


class LayoutPosition(Position):
    node_id: str = Field(min_length=1, max_length=300)


class LayoutUpdate(BaseModel):
    positions: list[LayoutPosition] = Field(default_factory=list, max_length=2000)
    viewport: Viewport | None = None


class NetworkInterfaceSource(StrEnum):
    SDEX = "sdex"
    MANUAL = "manual"
    SDEX_WITH_MANUAL_PREFIX = "sdex_with_manual_prefix"
    MOCK = "mock"


class AssignmentSource(StrEnum):
    EXPLICIT = "explicit"
    MANUAL_OVERRIDE = "manual_override"
    SUBNET = "subnet"
    GATEWAY_LOCAL = "gateway_local"
    UNRESOLVED = "unresolved"


class NetworkAddress(BaseModel):
    address: str = Field(min_length=2, max_length=64)
    prefix_length: int | None = Field(default=None, ge=0, le=128)
    network: str | None = None
    version: Literal[4, 6] | None = None

    @model_validator(mode="after")
    def normalize_literal_address(self) -> NetworkAddress:
        try:
            parsed = ip_address(self.address.strip())
        except ValueError as exc:
            raise ValueError("address must be a literal IPv4 or IPv6 address") from exc
        max_prefix = 32 if parsed.version == 4 else 128
        if self.prefix_length is not None and self.prefix_length > max_prefix:
            raise ValueError(
                f"prefix_length must be between 0 and {max_prefix} for IPv{parsed.version}"
            )
        canonical = str(parsed)
        calculated_network = (
            str(ip_network(f"{canonical}/{self.prefix_length}", strict=False))
            if self.prefix_length is not None
            else None
        )
        if self.version is not None and self.version != parsed.version:
            raise ValueError("version does not match address")
        if self.network is not None:
            try:
                supplied_network = str(ip_network(self.network.strip(), strict=True))
            except ValueError as exc:
                raise ValueError("network must be a canonical CIDR network") from exc
            if calculated_network is None or supplied_network != calculated_network:
                raise ValueError("network does not match address and prefix_length")
        self.address = canonical
        self.version = parsed.version
        self.network = calculated_network
        return self


class ManualNetworkAddress(BaseModel):
    address: str = Field(min_length=2, max_length=64)
    prefix_length: int | None = Field(default=None, ge=0, le=128)
    netmask: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def normalize_literal_address(self) -> ManualNetworkAddress:
        try:
            parsed = ip_address(self.address.strip())
        except ValueError as exc:
            raise ValueError("address must be a literal IPv4 or IPv6 address") from exc
        prefix_from_mask: int | None = None
        if self.netmask is not None:
            try:
                if parsed.version == 4:
                    mask_network = ip_network(
                        f"0.0.0.0/{self.netmask.strip()}",
                        strict=False,
                    )
                    prefix_from_mask = mask_network.prefixlen
                    self.netmask = str(mask_network.netmask)
                else:
                    prefix_from_mask = int(self.netmask)
                    self.netmask = str(prefix_from_mask)
            except (TypeError, ValueError) as exc:
                raise ValueError("netmask is not valid for the address family") from exc
        if self.prefix_length is None:
            self.prefix_length = prefix_from_mask
        elif prefix_from_mask is not None and self.prefix_length != prefix_from_mask:
            raise ValueError("prefix_length and netmask do not describe the same network")
        if self.prefix_length is None:
            raise ValueError("prefix_length or netmask is required")
        normalized = NetworkAddress(
            address=str(parsed),
            prefix_length=self.prefix_length,
        )
        self.address = normalized.address
        # Prefix length is the canonical persisted representation. Netmask is
        # accepted as an input convenience but is not stored as duplicate state.
        self.netmask = None
        return self


class ManualNetworkInterface(BaseModel):
    name: Literal["eth1", "eth2"]
    addresses: list[ManualNetworkAddress] = Field(min_length=1, max_length=16)

    @field_validator("addresses")
    @classmethod
    def unique_addresses(
        cls,
        addresses: list[ManualNetworkAddress],
    ) -> list[ManualNetworkAddress]:
        keys = {(address.address, address.prefix_length) for address in addresses}
        if len(keys) != len(addresses):
            raise ValueError("network interface addresses must be unique")
        return addresses


class NetworkInterface(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    addresses: list[NetworkAddress] = Field(default_factory=list, max_length=32)
    source: NetworkInterfaceSource = NetworkInterfaceSource.SDEX


class InterfaceAssignment(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    resolved: bool = False
    interface_name: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.:-]{1,64}$",
    )
    source: AssignmentSource = AssignmentSource.UNRESOLVED
    reason: str = Field(min_length=1, max_length=500)
    candidate_interfaces: list[Literal["eth1", "eth2"]] = Field(
        default_factory=list,
        max_length=2,
    )

    @model_validator(mode="after")
    def consistent_resolution(self) -> InterfaceAssignment:
        if self.resolved != (self.interface_name is not None):
            raise ValueError("resolved assignments require an interface_name")
        if self.resolved and self.source == AssignmentSource.UNRESOLVED:
            raise ValueError("a resolved assignment cannot use the unresolved source")
        if not self.resolved and self.source not in {
            AssignmentSource.UNRESOLVED,
            AssignmentSource.GATEWAY_LOCAL,
        }:
            raise ValueError("an unresolved assignment must use the unresolved source")
        if self.resolved and self.candidate_interfaces:
            raise ValueError("resolved assignments cannot expose interface candidates")
        if len(self.candidate_interfaces) != len(set(self.candidate_interfaces)):
            raise ValueError("candidate interfaces must be unique")
        return self


def _normalize_hex_color(value: str) -> str:
    normalized = value.upper()
    if (
        len(normalized) != 7
        or not normalized.startswith("#")
        or any(character not in "0123456789ABCDEF" for character in normalized[1:])
    ):
        raise ValueError("color must use the strict #RRGGBB hexadecimal format")
    return normalized


class EdgeVisualStyleUpdate(BaseModel):
    sheath_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    flow_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    reverse_flow: bool = Field(default=False, strict=True)

    @field_validator("sheath_color", "flow_color")
    @classmethod
    def strict_hex_color(cls, value: str) -> str:
        return _normalize_hex_color(value)


class EdgeVisualStyle(EdgeVisualStyleUpdate):
    edge_id: str = Field(
        min_length=9,
        max_length=320,
        pattern=r"^(?:sdex-to-[A-Za-z0-9_.:-]+|visual-link:[A-Za-z0-9_.:-]+)$",
    )
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)


class InterfaceOverrideUpdate(BaseModel):
    interface_name: Literal["eth1", "eth2"]


class ConnectionInterfaceOverride(InterfaceOverrideUpdate):
    connection_id: str = Field(
        min_length=1,
        max_length=300,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    updated_at: datetime


class DeviceVisualRoutingUpdate(BaseModel):
    source_handle: Literal["top", "right", "bottom", "left"]


class DeviceVisualRouting(BaseModel):
    connection_id: str = Field(
        min_length=1,
        max_length=300,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    preferred_source_handle: Literal["top", "right", "bottom", "left"]
    updated_at: datetime


class ConnectionNode(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    type: ConnectionType
    subtype: str | None = None
    display_name: str
    address: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=0, le=65535)
    endpoint_url: str | None = None
    enabled: bool
    licensed: bool | None = None
    status: ConnectionStatus
    status_reason: str | None = None
    source_module: str
    icon: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: datetime | None = None
    last_status_change_at: datetime | None = None
    stale: bool = False
    capabilities: dict[str, Any] = Field(default_factory=dict)
    interface_assignment: InterfaceAssignment | None = None
    local_service: bool = False
    interface_scope: Literal["gateway-local", "single-external"] | None = None
    session_telemetry: (
        Literal[
            "unavailable",
            "unknown",
            "connected",
            "disconnected",
        ]
        | None
    ) = None

    @field_validator("address", "host", "endpoint_url")
    @classmethod
    def safe_endpoint_display(cls, value: str | None) -> str | None:
        return public_endpoint(value)


class AggregateSummary(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    status: ConnectionStatus = ConnectionStatus.UNKNOWN
    total: int = Field(default=0, ge=0)
    connected: int = Field(default=0, ge=0)
    disconnected: int = Field(default=0, ge=0)
    disabled: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)
    degraded: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)
    animated: bool = False


class EdgeWaypoint(Position):
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: WaypointKind = WaypointKind.FREE
    order: int = Field(default=0, ge=0, le=63)


class EdgeRouteUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    routing_mode: EdgeRoutingMode
    waypoints: list[EdgeWaypoint] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def consistent_route(self) -> EdgeRouteUpdate:
        if self.routing_mode == EdgeRoutingMode.AUTO and self.waypoints:
            raise ValueError("auto routing cannot contain waypoints")
        waypoint_ids = [waypoint.id for waypoint in self.waypoints]
        if len(waypoint_ids) != len(set(waypoint_ids)):
            raise ValueError("waypoint ids must be unique")
        return self


class EdgeRoute(EdgeRouteUpdate):
    edge_id: str = Field(min_length=1, max_length=320, pattern=r"^[A-Za-z0-9_.:-]+$")
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)


class VisualElement(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^(?:rack|switch):[0-9a-f-]{32,36}$",
    )
    type: VisualElementType
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    position: Position
    width: float = Field(ge=120, le=20_000)
    height: float = Field(ge=100, le=20_000)
    external_interface: Literal["eth1", "eth2"] | None = None
    rows: int | None = Field(default=None, ge=1, le=10)
    columns: int | None = Field(default=None, ge=1, le=10)
    capacity: int | None = Field(default=None, ge=1, le=100)
    collapsed: bool = False
    icon: str | None = None
    status_mode: Literal["neutral", "aggregate"] = "neutral"
    aggregate: AggregateSummary | None = None
    derived_external_interface: Literal["eth1", "eth2"] | None = None
    effective_external_interface: Literal["eth1", "eth2"] | None = None
    interface_conflict: bool = False
    schema_version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def consistent_element(self) -> VisualElement:
        if self.type == VisualElementType.RACK:
            if self.rows is None or self.columns is None:
                raise ValueError("rack elements require rows and columns")
            self.capacity = self.rows * self.columns
            self.icon = None
            self.status_mode = "aggregate"
        else:
            if self.rows is not None or self.columns is not None or self.capacity is not None:
                raise ValueError("switch elements cannot define a rack matrix")
            self.collapsed = False
            self.icon = "/icons/Switch.svg"
        return self


class VisualElementCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    type: VisualElementType
    id: str | None = Field(
        default=None,
        min_length=8,
        max_length=80,
        pattern=r"^(?:rack|switch):[0-9a-f-]{32,36}$",
    )
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    position: Position
    rows: int | None = Field(default=None, ge=1, le=10)
    columns: int | None = Field(default=None, ge=1, le=10)
    external_interface: Literal["eth1", "eth2"] | None = None
    status_mode: Literal["neutral", "aggregate"] = "neutral"

    @model_validator(mode="after")
    def valid_type_fields(self) -> VisualElementCreate:
        if self.type == VisualElementType.SWITCH and (
            self.rows is not None or self.columns is not None
        ):
            raise ValueError("switch elements cannot define rows or columns")
        if self.id is not None and not self.id.startswith(f"{self.type}:"):
            raise ValueError("visual element id prefix must match its type")
        return self


class VisualElementUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    position: Position | None = None
    rows: int | None = Field(default=None, ge=1, le=10)
    columns: int | None = Field(default=None, ge=1, le=10)
    collapsed: bool | None = None
    external_interface: Literal["eth1", "eth2"] | None = None
    status_mode: Literal["neutral", "aggregate"] | None = None
    overflow_policy: Literal["reject", "eject"] = "reject"


class RackMemberUpdate(BaseModel):
    connection_id: str = Field(
        min_length=1,
        max_length=300,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    row: int = Field(ge=0, le=9)
    column: int = Field(ge=0, le=9)
    allow_unresolved_interface: bool = Field(default=False, strict=True)


class RackMembership(BaseModel):
    rack_id: str
    connection_id: str
    row: int = Field(ge=0, le=9)
    column: int = Field(ge=0, le=9)
    missing: bool = False
    connection: ConnectionNode | None = None
    unresolved_interface_confirmed: bool = False
    cached_display_name: str | None = None
    cached_connection_type: str | None = None
    cached_subtype: str | None = None
    cached_icon: str | None = None
    created_at: datetime
    updated_at: datetime


class VisualLinkCreate(BaseModel):
    id: str | None = Field(
        default=None,
        min_length=13,
        max_length=80,
        pattern=r"^visual-link:[0-9a-f-]{32,36}$",
    )
    source: str = Field(min_length=1, max_length=300, pattern=r"^[A-Za-z0-9_.:-]+$")
    target: str = Field(min_length=1, max_length=300, pattern=r"^[A-Za-z0-9_.:-]+$")
    source_handle: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    target_handle: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    external_interface: Literal["eth1", "eth2"] | None = None
    allow_unresolved_interface: bool = Field(default=False, strict=True)


class VisualLinkUpdate(BaseModel):
    target: str | None = Field(
        default=None, min_length=1, max_length=300, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    source_handle: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    target_handle: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    external_interface: Literal["eth1", "eth2"] | None = None
    allow_unresolved_interface: bool = Field(default=False, strict=True)


class VisualLink(BaseModel):
    id: str = Field(
        min_length=13,
        max_length=80,
        pattern=r"^visual-link:[0-9a-f-]{32,36}$",
    )
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    external_interface: Literal["eth1", "eth2"] | None = None
    unresolved_interface_confirmed: bool = False
    schema_version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime


class VisualTopologyState(BaseModel):
    elements: list[VisualElement] = Field(default_factory=list)
    rack_memberships: list[RackMembership] = Field(default_factory=list)
    links: list[VisualLink] = Field(default_factory=list)
    routes: dict[str, EdgeRoute] = Field(default_factory=dict)
    unrouted_connection_ids: list[str] = Field(default_factory=list)


class SystemInfo(BaseModel):
    product_type: str | None = None
    api_version: str | None = None
    status: str | None = None
    fqdn: str | None = None
    hostname: str | None = None
    http_api: str | bool | None = None
    os: str | None = None
    arch: str | None = None
    demo: bool | None = None
    all_connected: bool | None = None


class ModuleResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    module: str
    status: ModuleStatus
    count: int = 0
    error: str | None = None
    duration_ms: float | None = None


class TopologySummary(BaseModel):
    total_configured: int = 0
    enabled: int = 0
    connected: int = 0
    disconnected: int = 0
    disabled: int = 0
    unknown_degraded: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


class LayoutState(BaseModel):
    positions: dict[str, Position] = Field(default_factory=dict)
    viewport: Viewport | None = None
    visual_version: int = Field(default=1, ge=1)


class TopologyEdge(BaseModel):
    id: str = Field(
        min_length=9,
        max_length=320,
        pattern=r"^(?:sdex-to-[A-Za-z0-9_.:-]+|visual-link:[A-Za-z0-9_.:-]+)$",
    )
    source: str = Field(min_length=1, max_length=300)
    target: str = Field(min_length=1, max_length=300)
    source_handle: str | None = Field(default=None, max_length=100)
    target_handle: str | None = Field(default=None, max_length=100)
    interface_assignment: InterfaceAssignment
    style: EdgeVisualStyle | None = None
    kind: Literal["source", "visual", "aggregate"] = "source"
    route: EdgeRoute | None = None
    aggregate: AggregateSummary | None = None


class ActiveAlarm(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(min_length=1, max_length=180, pattern=r"^[A-Za-z0-9_.:-]+$")
    severity: AlarmSeverity
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    source: str | None = Field(default=None, max_length=120)
    occurred_at: datetime | None = None


class TopologySnapshot(BaseModel):
    gateway: ConnectionNode
    nodes: list[ConnectionNode] = Field(default_factory=list)
    module_results: list[ModuleResult] = Field(default_factory=list)
    summary: TopologySummary = Field(default_factory=TopologySummary)
    generated_at: datetime | None = None
    last_successful_refresh: datetime | None = None
    stale: bool = False
    partial: bool = False
    refresh_in_progress: bool = False
    last_error: str | None = None
    mock_mode: bool = False
    layout: LayoutState = Field(default_factory=LayoutState)
    network_interfaces: list[NetworkInterface] = Field(default_factory=list)
    edges: list[TopologyEdge] = Field(default_factory=list)
    visual_topology: VisualTopologyState = Field(default_factory=VisualTopologyState)
    alarms: list[ActiveAlarm] = Field(default_factory=list)


class ConnectionProfile(BaseModel):
    base_url: str
    username: str
    password: SecretStr
    verify_tls: bool = True
    timeout_seconds: float = Field(default=15, ge=1, le=120)
    source: Literal["database", "environment"] = "database"
    ca_cert_path: Path | None = None

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        return normalize_base_url(value)


class ConfigTestRequest(BaseModel):
    base_url: str
    username: str = Field(min_length=1, max_length=256)
    password: SecretStr | None = None
    verify_tls: bool = True
    timeout_seconds: float = Field(default=15, ge=1, le=120)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        return normalize_base_url(value)

    @field_validator("password")
    @classmethod
    def non_empty_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value():
            return None
        return value


class ConfigUpdateRequest(BaseModel):
    base_url: str
    username: str = Field(min_length=1, max_length=256)
    password: SecretStr | None = None
    verify_tls: bool = True
    timeout_seconds: float = Field(default=15, ge=1, le=120)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        return normalize_base_url(value)

    @field_validator("password")
    @classmethod
    def normalize_empty_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value():
            return None
        return value


class ConfigStatus(BaseModel):
    configured: bool
    source: Literal["database", "environment", "mock", "none"]
    base_url: str | None = None
    username: str | None = None
    verify_tls: bool = True
    timeout_seconds: float = 15
    password_configured: bool = False
    mock_mode: bool = False
    tls_warning: bool = False


class ConfigTestResponse(BaseModel):
    ok: Literal[True] = True
    system: SystemInfo


class DisplaySettings(BaseModel):
    refresh_interval_seconds: int = 300
    allowed_refresh_intervals: list[int] = Field(
        default_factory=lambda: list(ALLOWED_REFRESH_INTERVALS)
    )
    show_not_enabled: bool = False
    theme: Literal["light", "dark", "system"] = "system"
    network_interfaces: list[ManualNetworkInterface] = Field(
        default_factory=list,
        max_length=2,
    )

    @field_validator("refresh_interval_seconds")
    @classmethod
    def allowed_interval(cls, value: int) -> int:
        if value not in ALLOWED_REFRESH_INTERVALS:
            raise ValueError("refresh interval is not supported")
        return value

    @field_validator("network_interfaces")
    @classmethod
    def unique_interface_names(
        cls,
        interfaces: list[ManualNetworkInterface],
    ) -> list[ManualNetworkInterface]:
        if len({interface.name for interface in interfaces}) != len(interfaces):
            raise ValueError("network interface names must be unique")
        return interfaces


class SettingsUpdate(BaseModel):
    refresh_interval_seconds: int | None = None
    show_not_enabled: bool | None = None
    theme: Literal["light", "dark", "system"] | None = None
    network_interfaces: list[ManualNetworkInterface] | None = Field(
        default=None,
        max_length=2,
    )

    @field_validator("refresh_interval_seconds")
    @classmethod
    def allowed_interval(cls, value: int | None) -> int | None:
        if value is not None and value not in ALLOWED_REFRESH_INTERVALS:
            raise ValueError("refresh interval is not supported")
        return value

    @field_validator("network_interfaces")
    @classmethod
    def unique_interface_names(
        cls,
        interfaces: list[ManualNetworkInterface] | None,
    ) -> list[ManualNetworkInterface] | None:
        if interfaces is not None and len({interface.name for interface in interfaces}) != len(
            interfaces
        ):
            raise ValueError("network interface names must be unique")
        return interfaces

    @model_validator(mode="after")
    def at_least_one_field(self) -> SettingsUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one setting is required")
        return self


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unconfigured"]
    database: Literal["ok", "error"]
    scheduler: Literal["running", "stopped"]
    configured: bool
    mock_mode: bool
    refresh_in_progress: bool
    last_successful_refresh: datetime | None = None
    version: str
