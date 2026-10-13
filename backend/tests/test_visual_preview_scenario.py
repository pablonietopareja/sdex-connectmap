from __future__ import annotations

import math
from itertools import combinations

from app.adapters import default_adapters
from app.core.config import KNOWN_MOCK_SCENARIOS
from app.models.schemas import ConnectionStatus, ConnectionType, ModuleStatus
from app.services.discovery import (
    LAYOUT_CARD_SLOT_HEIGHT,
    LAYOUT_CARD_SLOT_WIDTH,
    LAYOUT_RING_RADIUS,
    MIN_LAYOUT_NODE_DISTANCE,
    DiscoveryService,
)
from app.services.events import EventBroker
from app.services.mock_sdex import (
    VISUAL_PREVIEW_FIXTURES,
    VISUAL_PREVIEW_NETWORK_INTERFACES_FIXTURE,
    VISUAL_PREVIEW_SYSTEM_FIXTURE,
    MockSDEXClient,
)
from app.services.sdex_client import NETWORK_INTERFACES_PATH

EXPECTED_CONNECTIONS = {
    ConnectionType.SIEMENS_S7_1200_1500: (
        "Packaging PLC",
        "192.168.10.11",
        102,
        "/icons/S7_2.svg",
    ),
    ConnectionType.SIEMENS_S7_300_400: (
        "Legacy Line PLC",
        "192.168.10.12",
        102,
        "/icons/S7.svg",
    ),
    ConnectionType.ROCKWELL_ALLEN_BRADLEY: (
        "Assembly ControlLogix",
        "192.168.10.13",
        44818,
        "/icons/Rockwell.svg",
    ),
    ConnectionType.MODBUS: (
        "Energy Meter",
        "192.168.10.14",
        502,
        "/icons/Modbus.svg",
    ),
    ConnectionType.SINUMERIK_840D: (
        "CNC Milling Center",
        "192.168.20.15",
        102,
        "/icons/Sinumerik.svg",
    ),
    ConnectionType.FANUC_CNC: (
        "Fanuc Machining Cell",
        "192.168.20.16",
        8193,
        "/icons/Fanuc.svg",
    ),
    ConnectionType.OPCUA_REMOTE_SERVER: (
        "Production OPC UA Server",
        "opc.tcp://192.168.20.17:4840",
        4840,
        "/icons/OPC_UA_Server.svg",
    ),
    ConnectionType.MQTT_BROKER: (
        "Factory MQTT Broker",
        "192.168.20.18",
        1883,
        "/icons/MQTT.svg",
    ),
}


def test_visual_preview_is_a_known_mock_scenario() -> None:
    assert "visual_preview" in KNOWN_MOCK_SCENARIOS


async def test_visual_preview_raw_fixtures_are_deterministic_and_use_adapters() -> None:
    first_client = MockSDEXClient("visual_preview")
    second_client = MockSDEXClient("visual_preview")

    assert await first_client.get_system() == VISUAL_PREVIEW_SYSTEM_FIXTURE
    assert await second_client.get_system() == VISUAL_PREVIEW_SYSTEM_FIXTURE
    assert (
        await first_client.get_json(NETWORK_INTERFACES_PATH)
        == VISUAL_PREVIEW_NETWORK_INTERFACES_FIXTURE
    )

    parsed_nodes = []
    for adapter in default_adapters():
        first_payload = await first_client.get_json(adapter.endpoint)
        second_payload = await second_client.get_json(adapter.endpoint)
        assert first_payload == second_payload == VISUAL_PREVIEW_FIXTURES[adapter.endpoint]
        parsed_nodes.extend(adapter.parse(first_payload))

    assert len(parsed_nodes) == 8
    assert {node.type for node in parsed_nodes} == set(EXPECTED_CONNECTIONS)
    assert all(node.status == ConnectionStatus.CONNECTED for node in parsed_nodes)


async def test_visual_preview_discovery_builds_exact_connected_topology(
    tmp_path,
    settings_factory,
    database,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    service = DiscoveryService(settings, database, EventBroker())
    try:
        snapshot = await service.refresh("visual_preview_test")
    finally:
        await service.close()

    assert snapshot.mock_mode is True
    assert snapshot.partial is False
    assert snapshot.stale is False
    assert snapshot.gateway.status == ConnectionStatus.CONNECTED
    assert snapshot.gateway.display_name == "SDEX Suite"
    assert snapshot.gateway.address == "sdex-edgenode.local"
    assert snapshot.gateway.icon == "/icons/SDEX.svg"
    assert snapshot.gateway.metadata == {
        "product_type": "SDEX Suite",
        "api_version": "1.0-preview",
        "status": "Running",
        "fqdn": "sdex-edgenode.local",
        "hostname": "sdex-edgenode",
        "http_api": "1.0",
        "os": "Linux",
        "arch": "amd64",
        "demo": False,
        "all_connected": True,
    }

    assert len(snapshot.nodes) == 8
    assert len(snapshot.edges) == 8
    assert snapshot.layout.visual_version == 2
    assert len(snapshot.layout.positions) == 9
    assert set(snapshot.layout.positions) == {
        snapshot.gateway.id,
        *(node.id for node in snapshot.nodes),
    }
    assert snapshot.summary.total_configured == 8
    assert snapshot.summary.enabled == 8
    assert snapshot.summary.connected == 8
    assert snapshot.summary.disabled == 0
    assert snapshot.summary.disconnected == 0
    assert snapshot.summary.unknown_degraded == 0
    assert all(result.status == ModuleStatus.OK for result in snapshot.module_results)
    assert sum(result.count for result in snapshot.module_results) == 8
    connection_positions = [snapshot.layout.positions[node.id] for node in snapshot.nodes]
    assert all(
        math.isclose(math.hypot(position.x, position.y), LAYOUT_RING_RADIUS)
        for position in connection_positions
    )
    assert all(
        math.hypot(first.x - second.x, first.y - second.y) >= MIN_LAYOUT_NODE_DISTANCE
        for first, second in combinations(connection_positions, 2)
    )
    assert all(
        not (
            abs(first.x - second.x) < LAYOUT_CARD_SLOT_WIDTH
            and abs(first.y - second.y) < LAYOUT_CARD_SLOT_HEIGHT
        )
        for first, second in combinations(connection_positions, 2)
    )
    assert {
        interface.name: {address.network for address in interface.addresses}
        for interface in snapshot.network_interfaces
    } == {
        "eth1": {"192.168.10.0/24"},
        "eth2": {"192.168.20.0/24"},
    }
    assignments = [
        node.interface_assignment.interface_name
        for node in snapshot.nodes
        if node.interface_assignment is not None
    ]
    assert assignments.count("eth1") == 4
    assert assignments.count("eth2") == 4
    assert all(edge.source != snapshot.gateway.id for edge in snapshot.edges)
    assert all(edge.target == snapshot.gateway.id for edge in snapshot.edges)
    assert {edge.target_handle for edge in snapshot.edges} == {
        "sdex-eth1",
        "sdex-eth2",
    }

    nodes_by_type = {node.type: node for node in snapshot.nodes}
    assert set(nodes_by_type) == set(EXPECTED_CONNECTIONS)
    for connection_type, expected in EXPECTED_CONNECTIONS.items():
        node = nodes_by_type[connection_type]
        expected_name, expected_address, expected_port, expected_icon = expected
        assert node.display_name == expected_name
        assert node.address == expected_address
        assert node.port == expected_port
        assert node.icon == expected_icon
        assert node.enabled is True
        assert node.licensed is True
        assert node.status == ConnectionStatus.CONNECTED
        assert node.stale is False

    sinumerik = nodes_by_type[ConnectionType.SINUMERIK_840D]
    assert sinumerik.capabilities["subchannels"] == {
        "nck": {"enabled": True, "status": "connected"},
        "plc": {"enabled": True, "status": "connected"},
    }
