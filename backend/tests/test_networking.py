from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.schemas import (
    AssignmentSource,
    ConnectionInterfaceOverride,
    ConnectionNode,
    ConnectionStatus,
    ConnectionType,
    EdgeVisualStyle,
    ManualNetworkAddress,
    ManualNetworkInterface,
    NetworkAddress,
    NetworkInterface,
    NetworkInterfaceSource,
)
from app.services.networking import (
    assign_interface,
    build_topology_edges,
    merge_network_interfaces,
    parse_network_interfaces,
)


def node(address: str | None, *, metadata=None, host: str | None = None) -> ConnectionNode:
    return ConnectionNode(
        id="modbus:meter",
        type=ConnectionType.MODBUS,
        display_name="Meter",
        address=address,
        host=host,
        enabled=True,
        status=ConnectionStatus.CONNECTED,
        source_module="modbus",
        icon="/icons/Modbus.svg",
        metadata=metadata or {},
    )


def interface(
    name: str,
    address: str,
    prefix_length: int | None,
) -> NetworkInterface:
    return NetworkInterface(
        name=name,
        addresses=[NetworkAddress(address=address, prefix_length=prefix_length)],
    )


def test_parse_netif_accepts_dynamic_and_record_shapes_without_inventing_prefixes() -> None:
    parsed = parse_network_interfaces(
        {
            "fqdn": "sdex.local",
            "hostname": "sdex",
            "ipv4": [
                {"eth1": "192.168.10.1/24"},
                {
                    "name": "eth2",
                    "address": "192.168.20.1",
                    "netmask": "255.255.255.0",
                },
                {"NetworkInterface": "10.0.0.1"},
            ],
            "ipv6": [{"eth1": "fd00:10::1/64"}],
        }
    )

    by_name = {item.name: item for item in parsed}
    assert by_name["eth1"].addresses[0].network == "192.168.10.0/24"
    assert {address.version for address in by_name["eth1"].addresses} == {4, 6}
    assert by_name["eth2"].addresses[0].prefix_length == 24
    # The official schema does not guarantee a concrete name for this key.
    assert "eth3" not in by_name
    assert by_name["NetworkInterface"].addresses[0].prefix_length is None


def test_manual_networks_fill_missing_prefix_and_can_supply_absent_interface() -> None:
    discovered = [
        interface("eth1", "192.168.10.1", None),
    ]
    configured = [
        ManualNetworkInterface(
            name="eth1",
            addresses=[ManualNetworkAddress(address="192.168.10.1", netmask="255.255.255.0")],
        ),
        ManualNetworkInterface(
            name="eth2",
            addresses=[ManualNetworkAddress(address="192.168.20.1", prefix_length=24)],
        ),
    ]

    merged = {item.name: item for item in merge_network_interfaces(discovered, configured)}
    assert merged["eth1"].source == NetworkInterfaceSource.SDEX_WITH_MANUAL_PREFIX
    assert merged["eth1"].addresses[0].network == "192.168.10.0/24"
    assert merged["eth2"].source == NetworkInterfaceSource.MANUAL


def test_subnet_assignment_uses_unique_longest_prefix_for_ipv4_and_ipv6() -> None:
    interfaces = [
        interface("eth1", "10.0.0.1", 8),
        NetworkInterface(
            name="eth2",
            addresses=[
                NetworkAddress(address="10.2.0.1", prefix_length=16),
                NetworkAddress(address="fd00:20::1", prefix_length=64),
            ],
        ),
    ]

    ipv4 = assign_interface(node("10.2.3.4"), interfaces)
    ipv6 = assign_interface(node("opc.tcp://[fd00:20::99]:4840", host="fd00:20::99"), interfaces)
    assert (ipv4.interface_name, ipv4.source) == ("eth2", AssignmentSource.SUBNET)
    assert (ipv6.interface_name, ipv6.source) == ("eth2", AssignmentSource.SUBNET)


def test_equal_longest_prefix_is_ambiguous_and_unresolved() -> None:
    assignment = assign_interface(
        node("192.168.1.50"),
        [
            interface("eth1", "192.168.1.1", 24),
            interface("eth2", "192.168.1.2", 24),
        ],
    )
    assert assignment.resolved is False
    assert assignment.source == AssignmentSource.UNRESOLVED
    assert "multiple" in assignment.reason


@pytest.mark.parametrize(
    ("candidate", "interfaces", "reason_fragment"),
    [
        (
            node("mqtt.internal", host="mqtt.internal"),
            [interface("eth1", "192.168.1.1", 24)],
            "hostnames are not resolved",
        ),
        (
            node("192.168.2.4"),
            [interface("eth1", "192.168.1.1", 24)],
            "does not match",
        ),
        (
            node("192.168.1.4"),
            [interface("eth1", "192.168.1.1", None)],
            "usable prefix",
        ),
    ],
)
def test_hostname_unmatched_and_prefix_absent_are_unresolved(
    candidate,
    interfaces,
    reason_fragment,
) -> None:
    assignment = assign_interface(candidate, interfaces)
    assert assignment.resolved is False
    assert reason_fragment in assignment.reason


def test_explicit_binding_precedes_override_and_override_precedes_subnet() -> None:
    interfaces = [
        interface("eth1", "192.168.10.1", 24),
        interface("eth2", "192.168.20.1", 24),
    ]
    override = ConnectionInterfaceOverride(
        connection_id="modbus:meter",
        interface_name="eth2",
        updated_at=datetime.now(UTC),
    )
    explicit = assign_interface(
        node("192.168.10.50", metadata={"NetworkAdapter": "eth1"}),
        interfaces,
        override,
    )
    overridden = assign_interface(node("192.168.10.50"), interfaces, override)
    assert (explicit.interface_name, explicit.source) == ("eth1", AssignmentSource.EXPLICIT)
    assert (overridden.interface_name, overridden.source) == (
        "eth2",
        AssignmentSource.MANUAL_OVERRIDE,
    )


def test_override_to_unavailable_interface_does_not_fall_back_or_get_persisted_as_derived() -> None:
    assignment = assign_interface(
        node("192.168.10.50"),
        [interface("eth1", "192.168.10.1", 24)],
        "eth2",
    )
    assert assignment.resolved is False
    assert "not currently configured" in assignment.reason


def test_edges_are_device_to_gateway_with_stable_handles_and_style_overlay() -> None:
    connection = node("192.168.20.50")
    edge_id = f"sdex-to-{connection.id}"
    style = EdgeVisualStyle(
        edge_id=edge_id,
        sheath_color="#112233",
        flow_color="#AABBCC",
        reverse_flow=True,
        updated_at=datetime.now(UTC),
    )
    nodes, edges = build_topology_edges(
        [connection],
        "sdex_gateway:sdex",
        [interface("eth2", "192.168.20.1", 24)],
        {},
        {edge_id: style},
    )

    assert nodes[0].interface_assignment is not None
    assert edges[0].model_dump(exclude={"interface_assignment", "style"}) == {
        "id": edge_id,
        "source": connection.id,
        "target": "sdex_gateway:sdex",
        "source_handle": None,
        "target_handle": "sdex-eth2",
        "kind": "source",
        "route": None,
        "aggregate": None,
    }
    assert edges[0].style == style
    assert edges[0].style.reverse_flow is True


def test_disabled_connections_keep_assignment_data_but_do_not_emit_a_cable() -> None:
    disabled = node("192.168.20.50").model_copy(
        update={"enabled": False, "status": ConnectionStatus.DISABLED}
    )
    nodes, edges = build_topology_edges(
        [disabled],
        "sdex_gateway:sdex",
        [interface("eth2", "192.168.20.1", 24)],
        {},
        {},
    )
    assert nodes[0].interface_assignment is not None
    assert nodes[0].interface_assignment.interface_name == "eth2"
    assert edges == []
