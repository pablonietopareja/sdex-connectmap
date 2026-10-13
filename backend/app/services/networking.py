from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import Any
from urllib.parse import urlsplit

from app.adapters.base import normalized_key
from app.models.schemas import (
    AssignmentSource,
    ConnectionInterfaceOverride,
    ConnectionNode,
    ConnectionStatus,
    DeviceVisualRouting,
    EdgeVisualStyle,
    InterfaceAssignment,
    ManualNetworkInterface,
    NetworkAddress,
    NetworkInterface,
    NetworkInterfaceSource,
    TopologyEdge,
)

SUPPORTED_SDEX_INTERFACES = frozenset({"eth1", "eth2"})
_INTERFACE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_NAME_KEYS = frozenset(
    {
        "name",
        "interface",
        "interfacename",
        "adapter",
        "adaptername",
        "networkadapter",
    }
)
_ADDRESS_KEYS = frozenset(
    {
        "address",
        "ip",
        "ipaddress",
        "ipv4",
        "ipv4address",
        "ipv6",
        "ipv6address",
    }
)
_PREFIX_KEYS = frozenset({"prefix", "prefixlength", "cidr", "cidrprefix"})
_NETMASK_KEYS = frozenset({"netmask", "mask", "subnetmask"})
_RESERVED_KEYS = _NAME_KEYS | _ADDRESS_KEYS | _PREFIX_KEYS | _NETMASK_KEYS


def _literal_ip(value: Any) -> IPv4Address | IPv6Address | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().strip("[]")
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    try:
        return ip_address(candidate)
    except ValueError:
        return None


def _address_and_prefix(
    value: Any,
    *,
    prefix: Any = None,
    netmask: Any = None,
) -> tuple[str, int | None] | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    embedded_prefix: int | None = None
    if "/" in candidate:
        raw_address, raw_prefix = candidate.rsplit("/", 1)
        parsed = _literal_ip(raw_address)
        try:
            embedded_prefix = int(raw_prefix)
        except ValueError:
            return None
    else:
        parsed = _literal_ip(candidate)
    if parsed is None:
        return None
    parsed_prefix = embedded_prefix
    if parsed_prefix is None and prefix is not None:
        try:
            parsed_prefix = int(prefix)
        except (TypeError, ValueError):
            return None
    if parsed_prefix is None and isinstance(netmask, str) and netmask.strip():
        try:
            if parsed.version == 4:
                parsed_prefix = ip_network(f"0.0.0.0/{netmask.strip()}").prefixlen
            else:
                parsed_prefix = int(netmask)
        except ValueError:
            return None
    max_prefix = 32 if parsed.version == 4 else 128
    if parsed_prefix is not None and not 0 <= parsed_prefix <= max_prefix:
        return None
    return str(parsed), parsed_prefix


def _mapping_value(mapping: Mapping[str, Any], keys: frozenset[str]) -> Any:
    for key, value in mapping.items():
        if normalized_key(str(key)) in keys:
            return value
    return None


def _append_address(
    collected: dict[str, list[NetworkAddress]],
    interface_name: Any,
    raw_address: Any,
    *,
    prefix: Any = None,
    netmask: Any = None,
) -> None:
    if not isinstance(interface_name, str):
        return
    name = interface_name.strip()
    if not _INTERFACE_NAME_PATTERN.fullmatch(name):
        return
    parsed = _address_and_prefix(raw_address, prefix=prefix, netmask=netmask)
    if parsed is None:
        return
    address, prefix_length = parsed
    normalized = NetworkAddress(address=address, prefix_length=prefix_length)
    addresses = collected.setdefault(name, [])
    if not any(
        existing.address == normalized.address
        and existing.prefix_length == normalized.prefix_length
        for existing in addresses
    ):
        addresses.append(normalized)


def _parse_record(
    collected: dict[str, list[NetworkAddress]],
    record: Any,
) -> None:
    if not isinstance(record, Mapping):
        return
    interface_name = _mapping_value(record, _NAME_KEYS)
    address_value = _mapping_value(record, _ADDRESS_KEYS)
    prefix = _mapping_value(record, _PREFIX_KEYS)
    netmask = _mapping_value(record, _NETMASK_KEYS)
    if interface_name is not None and address_value is not None:
        if isinstance(address_value, Sequence) and not isinstance(
            address_value,
            str | bytes | bytearray,
        ):
            for address in address_value:
                _append_address(
                    collected,
                    interface_name,
                    address,
                    prefix=prefix,
                    netmask=netmask,
                )
        else:
            _append_address(
                collected,
                interface_name,
                address_value,
                prefix=prefix,
                netmask=netmask,
            )
        return

    # The published SDEX schema leaves the per-interface object shape loose.
    # Accept dynamic interface-name keys, but never infer names from array order.
    for key, value in record.items():
        if normalized_key(str(key)) in _RESERVED_KEYS:
            continue
        if isinstance(value, Mapping):
            nested_address = _mapping_value(value, _ADDRESS_KEYS)
            nested_prefix = _mapping_value(value, _PREFIX_KEYS)
            nested_netmask = _mapping_value(value, _NETMASK_KEYS)
            _append_address(
                collected,
                str(key),
                nested_address,
                prefix=nested_prefix,
                netmask=nested_netmask,
            )
        elif isinstance(value, Sequence) and not isinstance(
            value,
            str | bytes | bytearray,
        ):
            for address in value:
                _append_address(collected, str(key), address)
        else:
            _append_address(collected, str(key), value)


def parse_network_interfaces(
    payload: Any,
    *,
    source: NetworkInterfaceSource = NetworkInterfaceSource.SDEX,
) -> list[NetworkInterface]:
    """Normalize documented and compatible-extra SDEX netif response shapes.

    Unknown entries are ignored. In particular, array position is never treated
    as an interface name and no prefix is fabricated.
    """

    if not isinstance(payload, Mapping):
        return []
    collected: dict[str, list[NetworkAddress]] = {}
    interface_records = _mapping_value(
        payload,
        frozenset({"interfaces", "networkinterfaces", "netinterfaces"}),
    )
    families = [
        _mapping_value(payload, frozenset({"ipv4"})),
        _mapping_value(payload, frozenset({"ipv6"})),
        interface_records,
    ]
    for family in families:
        if isinstance(family, Mapping):
            _parse_record(collected, family)
        elif isinstance(family, Sequence) and not isinstance(
            family,
            str | bytes | bytearray,
        ):
            for record in family:
                _parse_record(collected, record)
    return [
        NetworkInterface(
            name=name,
            addresses=sorted(
                addresses,
                key=lambda item: (
                    item.version or 0,
                    item.address,
                    item.prefix_length if item.prefix_length is not None else -1,
                ),
            ),
            source=source,
        )
        for name, addresses in sorted(collected.items())
    ]


def manual_network_interfaces(
    configured: Sequence[ManualNetworkInterface],
) -> list[NetworkInterface]:
    return [
        NetworkInterface(
            name=interface.name,
            addresses=[
                NetworkAddress(
                    address=address.address,
                    prefix_length=address.prefix_length,
                )
                for address in interface.addresses
            ],
            source=NetworkInterfaceSource.MANUAL,
        )
        for interface in configured
    ]


def merge_network_interfaces(
    discovered: Sequence[NetworkInterface],
    configured: Sequence[ManualNetworkInterface],
) -> list[NetworkInterface]:
    """Add explicit manual networks only where SDEX lacks usable prefix data."""

    manual_by_name = {manual.name: manual for manual in manual_network_interfaces(configured)}
    merged: list[NetworkInterface] = []
    discovered_names: set[str] = set()
    for interface in discovered:
        discovered_names.add(interface.name)
        manual = manual_by_name.get(interface.name)
        manual_by_address = (
            {address.address: address for address in manual.addresses} if manual is not None else {}
        )
        addresses: list[NetworkAddress] = []
        manual_used = False
        for address in interface.addresses:
            replacement = manual_by_address.get(address.address)
            if address.prefix_length is None and replacement is not None:
                addresses.append(replacement)
                manual_used = True
            else:
                addresses.append(address)
        if manual is not None:
            existing = {(address.address, address.version) for address in addresses}
            for manual_address in manual.addresses:
                key = (manual_address.address, manual_address.version)
                if key not in existing:
                    addresses.append(manual_address)
                    manual_used = True
        merged_source = interface.source
        if manual_used and interface.source != NetworkInterfaceSource.MOCK:
            merged_source = NetworkInterfaceSource.SDEX_WITH_MANUAL_PREFIX
        merged.append(
            NetworkInterface(
                name=interface.name,
                addresses=addresses,
                source=merged_source,
            )
        )
    for name, interface in manual_by_name.items():
        if name not in discovered_names:
            merged.append(interface)
    return sorted(merged, key=lambda interface: interface.name)


def literal_node_address(
    node: ConnectionNode,
) -> IPv4Address | IPv6Address | None:
    for candidate in (node.host, node.address):
        parsed = _literal_ip(candidate)
        if parsed is not None:
            return parsed
    if node.endpoint_url:
        try:
            hostname = urlsplit(node.endpoint_url).hostname
        except ValueError:
            hostname = None
        parsed = _literal_ip(hostname)
        if parsed is not None:
            return parsed
    return None


def _explicit_interface(node: ConnectionNode, available: set[str]) -> str | None:
    for key, value in node.metadata.items():
        if normalized_key(str(key)) not in {
            "interface",
            "interfacename",
            "networkadapter",
        }:
            continue
        if isinstance(value, str):
            candidate = value.strip()
            if candidate in available or (
                node.local_service
                and node.interface_scope == "single-external"
                and candidate in SUPPORTED_SDEX_INTERFACES
            ):
                return candidate
    return None


def assign_interface(
    node: ConnectionNode,
    interfaces: Sequence[NetworkInterface],
    override: ConnectionInterfaceOverride | str | None = None,
) -> InterfaceAssignment:
    available = {
        interface.name for interface in interfaces if interface.name in SUPPORTED_SDEX_INTERFACES
    }
    explicit = _explicit_interface(node, available)
    if explicit is not None:
        return InterfaceAssignment(
            resolved=True,
            interface_name=explicit,
            source=AssignmentSource.EXPLICIT,
            reason=f"SDEX explicitly binds this connection to {explicit}.",
        )

    override_name = (
        override.interface_name if isinstance(override, ConnectionInterfaceOverride) else override
    )
    if override_name is not None:
        if override_name in available:
            return InterfaceAssignment(
                resolved=True,
                interface_name=override_name,
                source=AssignmentSource.MANUAL_OVERRIDE,
                reason=f"A saved manual override selects {override_name}.",
            )
        return InterfaceAssignment(
            reason=(
                f"The saved manual override selects {override_name}, but that "
                "interface is not currently configured."
            )
        )

    if node.local_service and node.interface_scope == "gateway-local":
        candidates = sorted(available)
        if len(candidates) == 1:
            return InterfaceAssignment(
                resolved=True,
                interface_name=candidates[0],
                source=AssignmentSource.GATEWAY_LOCAL,
                reason=(
                    "The gateway-local service is available through the only "
                    f"configured external interface, {candidates[0]}."
                ),
            )
        return InterfaceAssignment(
            resolved=False,
            source=AssignmentSource.GATEWAY_LOCAL,
            candidate_interfaces=candidates,
            reason=(
                "The service is hosted by SDEX and is available through all configured "
                "logical external interfaces; no single physical port is asserted."
            ),
        )

    device_address = literal_node_address(node)
    if device_address is None:
        return InterfaceAssignment(
            reason=(
                "The connection does not expose a literal IP address; hostnames "
                "are not resolved automatically."
            )
        )

    candidates: list[tuple[int, str]] = []
    usable_prefix_seen = False
    for interface in interfaces:
        if interface.name not in SUPPORTED_SDEX_INTERFACES:
            continue
        for address in interface.addresses:
            if address.prefix_length is None or address.version != device_address.version:
                continue
            usable_prefix_seen = True
            network = ip_network(
                f"{address.address}/{address.prefix_length}",
                strict=False,
            )
            if device_address in network:
                candidates.append((network.prefixlen, interface.name))
    if not usable_prefix_seen:
        return InterfaceAssignment(
            reason=(
                "No eth1/eth2 address has a usable prefix; configure an explicit "
                "prefix or a manual override."
            )
        )
    if not candidates:
        return InterfaceAssignment(
            reason="The connection address does not match any configured eth1/eth2 subnet."
        )
    longest_prefix = max(prefix for prefix, _name in candidates)
    best_names = {name for prefix, name in candidates if prefix == longest_prefix}
    if len(best_names) != 1:
        return InterfaceAssignment(
            reason=(
                "The connection address matches multiple interfaces with the same longest prefix."
            )
        )
    selected = next(iter(best_names))
    return InterfaceAssignment(
        resolved=True,
        interface_name=selected,
        source=AssignmentSource.SUBNET,
        reason=f"The literal IP address matches {selected} by longest-prefix subnet.",
    )


def build_topology_edges(
    nodes: Sequence[ConnectionNode],
    gateway_id: str,
    interfaces: Sequence[NetworkInterface],
    overrides: Mapping[str, ConnectionInterfaceOverride],
    styles: Mapping[str, EdgeVisualStyle],
    visual_routings: Mapping[str, DeviceVisualRouting] | None = None,
) -> tuple[list[ConnectionNode], list[TopologyEdge]]:
    visual_routings = visual_routings or {}
    enriched_nodes: list[ConnectionNode] = []
    edges: list[TopologyEdge] = []
    for node in nodes:
        assignment = assign_interface(node, interfaces, overrides.get(node.id))
        enriched = node.model_copy(update={"interface_assignment": assignment})
        enriched_nodes.append(enriched)
        if not node.enabled or node.status == ConnectionStatus.DISABLED:
            continue
        edge_id = f"sdex-to-{node.id}"
        routing = visual_routings.get(node.id)
        target_handle = (
            f"sdex-{assignment.interface_name}"
            if assignment.interface_name in SUPPORTED_SDEX_INTERFACES
            else None
        )
        edges.append(
            TopologyEdge(
                id=edge_id,
                source=node.id,
                target=gateway_id,
                source_handle=(routing.preferred_source_handle if routing else None),
                target_handle=target_handle,
                interface_assignment=assignment,
                style=styles.get(edge_id),
            )
        )
    return enriched_nodes, edges


def interface_names(interfaces: Iterable[NetworkInterface]) -> set[str]:
    return {interface.name for interface in interfaces}
