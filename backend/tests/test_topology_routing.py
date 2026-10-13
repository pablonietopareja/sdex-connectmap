from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.adapters.opcua import OpcUaServerAdapter
from app.core.security import CredentialCipher
from app.main import create_app
from app.models.schemas import (
    ActiveAlarm,
    AlarmSeverity,
    AssignmentSource,
    ConnectionNode,
    ConnectionStatus,
    ConnectionType,
    EdgeRouteUpdate,
    EdgeVisualStyleUpdate,
    InterfaceAssignment,
    ModuleResult,
    ModuleStatus,
    NetworkAddress,
    NetworkInterface,
    Position,
    TopologySnapshot,
    VisualElement,
    VisualLink,
)
from app.persistence import Database
from app.services.alarms import build_active_alarms, deduplicate_alarms
from app.services.networking import assign_interface, build_topology_edges
from app.services.visual_topology import VisualTopologyService, aggregate_topology_state

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _refreshed(client: TestClient) -> dict:
    assert client.post("/api/topology/refresh").status_code == 202
    for _attempt in range(120):
        payload = client.get("/api/topology").json()
        if payload["nodes"] and not payload["refresh_in_progress"]:
            return payload
        client.portal.call(asyncio.sleep, 0.02)
    raise AssertionError("mock topology did not finish refreshing")


def _gateway() -> ConnectionNode:
    return ConnectionNode(
        id="sdex_gateway:sdex",
        type=ConnectionType.SDEX_GATEWAY,
        display_name="SDEX",
        enabled=True,
        status=ConnectionStatus.CONNECTED,
        source_module="core",
        icon="/icons/SDEX.svg",
    )


def _node(
    node_id: str,
    status: ConnectionStatus = ConnectionStatus.CONNECTED,
    interface: str = "eth2",
) -> ConnectionNode:
    return ConnectionNode(
        id=node_id,
        type=ConnectionType.MODBUS,
        display_name=node_id,
        address="192.168.0.100",
        enabled=True,
        status=status,
        source_module="modbus",
        icon="/icons/Modbus.svg",
        interface_assignment=InterfaceAssignment(
            resolved=True,
            interface_name=interface,
            source=AssignmentSource.SUBNET,
            reason="fixture",
        ),
    )


def _switch(*, external_interface: str | None = None) -> VisualElement:
    return VisualElement(
        id="switch:00000000-0000-4000-8000-000000000701",
        type="switch",
        name="Prompt 7 Switch",
        position=Position(x=100, y=200),
        width=310,
        height=228,
        external_interface=external_interface,
        status_mode="neutral",
        created_at=NOW,
        updated_at=NOW,
    )


def _link(link_id: int, source: str, target: str, interface: str | None) -> VisualLink:
    return VisualLink(
        id=f"visual-link:00000000-0000-4000-8000-{link_id:012d}",
        source=source,
        target=target,
        external_interface=interface,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    "address",
    ["localhost", "127.0.0.1", "::1", "opc.tcp://[::1]:4897"],
)
def test_enabled_loopback_opcua_endpoint_is_gateway_local(address: str) -> None:
    record = {"name": "Default", "address": address, "port": 4897, "Enabled": True}
    parsed = OpcUaServerAdapter().parse([record], observed_at=NOW)[0]

    assert parsed.status == ConnectionStatus.CONNECTED
    assert parsed.local_service is True
    assert parsed.interface_scope == "gateway-local"
    assert parsed.session_telemetry == "unavailable"
    assert parsed.capabilities["active_incoming_session_telemetry"] == "unavailable"
    assert "does not expose active incoming" in (parsed.status_reason or "")


def test_gateway_local_assignment_uses_only_logical_external_interfaces() -> None:
    local = OpcUaServerAdapter().parse(
        [{"name": "Default", "address": "localhost", "Enabled": True}],
        observed_at=NOW,
    )[0]
    docker_only = [
        NetworkInterface(
            name="eth0",
            addresses=[NetworkAddress(address="172.18.0.2", prefix_length=16)],
        ),
        NetworkInterface(
            name="lo",
            addresses=[NetworkAddress(address="127.0.0.1", prefix_length=8)],
        ),
    ]
    assignment = assign_interface(local, docker_only)
    assert assignment.resolved is False
    assert assignment.source == AssignmentSource.GATEWAY_LOCAL
    assert assignment.candidate_interfaces == []
    assert assignment.interface_name is None

    external = docker_only + [
        NetworkInterface(
            name="eth1",
            addresses=[NetworkAddress(address="192.168.0.10", prefix_length=24)],
        ),
        NetworkInterface(
            name="eth2",
            addresses=[NetworkAddress(address="10.10.0.10", prefix_length=24)],
        ),
    ]
    assignment = assign_interface(local, external)
    assert assignment.resolved is False
    assert assignment.candidate_interfaces == ["eth1", "eth2"]


def test_gateway_local_explicit_binding_has_priority() -> None:
    local = OpcUaServerAdapter().parse(
        [
            {
                "name": "Default",
                "address": "127.0.0.1",
                "Enabled": True,
                "interface": "eth2",
            }
        ],
        observed_at=NOW,
    )[0]
    assignment = assign_interface(local, [])
    assert local.interface_scope == "single-external"
    assert assignment.resolved is True
    assert assignment.interface_name == "eth2"
    assert assignment.source == AssignmentSource.EXPLICIT


@pytest.mark.asyncio
async def test_device_visual_routing_survives_restart_and_source_refresh(tmp_path) -> None:
    key = Fernet.generate_key()
    path = tmp_path / "routing.db"
    database = Database(path, CredentialCipher(key))
    await database.initialize()
    saved = await database.save_device_visual_routing("modbus:cabinet", "bottom")
    assert saved.preferred_source_handle == "bottom"

    restarted = Database(path, CredentialCipher(key))
    await restarted.initialize()
    loaded = await restarted.load_device_visual_routings()
    assert loaded["modbus:cabinet"].preferred_source_handle == "bottom"

    nodes, edges = build_topology_edges(
        [_node("modbus:cabinet")],
        _gateway().id,
        [
            NetworkInterface(
                name="eth2",
                addresses=[NetworkAddress(address="192.168.0.10", prefix_length=24)],
            )
        ],
        {},
        {},
        loaded,
    )
    assert nodes[0].id == "modbus:cabinet"
    assert edges[0].id == "sdex-to-modbus:cabinet"
    assert edges[0].source_handle == "bottom"
    assert edges[0].target_handle == "sdex-eth2"


def test_reanchor_api_keeps_logical_edge_style_route_and_target(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = _refreshed(client)
        edge = next(item for item in topology["edges"] if item["kind"] == "source")
        connection_id = edge["source"]
        edge_id = edge["id"]
        target_handle = edge["target_handle"]
        assert (
            client.put(
                f"/api/edges/{edge_id}/style",
                json={
                    "sheath_color": "#123456",
                    "flow_color": "#ABCDEF",
                    "reverse_flow": True,
                },
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/edges/{edge_id}/route",
                json={
                    "routing_mode": "manual",
                    "waypoints": [{"id": "same", "x": 20, "y": 30}],
                },
            ).status_code
            == 200
        )
        changed = client.put(
            f"/api/connections/{connection_id}/visual-routing",
            json={"source_handle": "bottom"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["preferred_source_handle"] == "bottom"

        refreshed = client.get("/api/topology").json()
        same = next(item for item in refreshed["edges"] if item["id"] == edge_id)
        assert same["source_handle"] == "bottom"
        assert same["target_handle"] == target_handle
        assert same["style"] == {
            "sheath_color": "#123456",
            "flow_color": "#ABCDEF",
            "reverse_flow": True,
            "edge_id": edge_id,
            "updated_at": same["style"]["updated_at"],
            "schema_version": 2,
        }
        assert same["route"]["routing_mode"] == "manual"
        assert same["route"]["waypoints"][0]["id"] == "same"
        assert not any(
            link["source"] == connection_id for link in refreshed["visual_topology"]["links"]
        )

        after_source_refresh = _refreshed(client)
        persisted = next(item for item in after_source_refresh["edges"] if item["id"] == edge_id)
        assert persisted["source_handle"] == "bottom"


def test_visual_routing_handle_validation(tmp_path, settings_factory) -> None:
    settings = settings_factory(tmp_path, mock_mode=True)
    with TestClient(create_app(settings)) as client:
        connection_id = _refreshed(client)["nodes"][0]["id"]
        invalid = client.put(
            f"/api/connections/{connection_id}/visual-routing",
            json={"source_handle": "diagonal"},
        )
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_v4_to_v5_migration_preserves_edge_presentation(tmp_path) -> None:
    key = Fernet.generate_key()
    path = tmp_path / "v4.db"
    original = Database(path, CredentialCipher(key))
    await original.initialize()
    edge_id = "sdex-to-modbus:legacy"
    await original.save_edge_style(
        edge_id,
        EdgeVisualStyleUpdate(
            sheath_color="#123456",
            flow_color="#ABCDEF",
            reverse_flow=True,
        ),
    )
    await original.save_edge_route(
        edge_id,
        EdgeRouteUpdate(
            routing_mode="manual",
            waypoints=[{"id": "legacy-bend", "x": 1, "y": 2}],
        ),
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE device_visual_routing")
        connection.execute("UPDATE schema_metadata SET version=4 WHERE singleton=1")

    migrated = Database(path, CredentialCipher(key))
    await migrated.initialize()
    assert await migrated.schema_version() == 5
    assert (await migrated.load_edge_styles())[edge_id].reverse_flow is True
    assert (await migrated.load_edge_styles())[edge_id].sheath_color == "#123456"
    assert (await migrated.load_visual_topology()).routes[edge_id].waypoints[0].id == "legacy-bend"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_visual_routing'"
        ).fetchone()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([ConnectionStatus.CONNECTED] * 3, ConnectionStatus.CONNECTED),
        (
            [ConnectionStatus.CONNECTED, ConnectionStatus.DISCONNECTED],
            ConnectionStatus.DEGRADED,
        ),
        ([ConnectionStatus.DISCONNECTED] * 2, ConnectionStatus.DISCONNECTED),
    ],
)
async def test_switch_uses_shared_aggregate_and_derives_interface(
    database,
    statuses,
    expected,
) -> None:
    visual_switch = _switch()
    await database.save_visual_element(visual_switch)
    nodes = [_node(f"modbus:child-{index}", status) for index, status in enumerate(statuses)]
    for index, child in enumerate(nodes, start=710):
        await database.save_visual_link(_link(index, child.id, visual_switch.id, "eth2"))
    uplink = _link(799, visual_switch.id, _gateway().id, None)
    await database.save_visual_link(uplink)
    snapshot = TopologySnapshot(gateway=_gateway(), nodes=nodes)
    service = VisualTopologyService(database)
    state = await service.state_for_snapshot(snapshot)
    switch_state = state.elements[0]
    assert switch_state.aggregate is not None
    assert switch_state.aggregate.status == expected
    assert switch_state.derived_external_interface == "eth2"
    assert switch_state.effective_external_interface == "eth2"
    assert switch_state.interface_conflict is False

    overlaid = await service.overlay(snapshot, snapshot.gateway, nodes, [], {})
    switch_edge = next(edge for edge in overlaid.edges if edge.id == uplink.id)
    assert switch_edge.target_handle == "sdex-eth2"
    assert switch_edge.aggregate is not None
    assert switch_edge.aggregate.status == expected


@pytest.mark.asyncio
async def test_switch_interface_conflict_and_explicit_override(database) -> None:
    visual_switch = _switch(external_interface="eth2")
    await database.save_visual_element(visual_switch)
    eth1 = _node("modbus:eth1", interface="eth1")
    eth2 = _node("modbus:eth2", interface="eth2")
    await database.save_visual_link(_link(801, eth1.id, visual_switch.id, "eth1"))
    await database.save_visual_link(_link(802, eth2.id, visual_switch.id, "eth2"))
    uplink = _link(803, visual_switch.id, _gateway().id, "eth1")
    await database.save_visual_link(uplink)
    snapshot = TopologySnapshot(gateway=_gateway(), nodes=[eth1, eth2])
    service = VisualTopologyService(database)
    state = await service.state_for_snapshot(snapshot)
    switch_state = state.elements[0]
    assert switch_state.derived_external_interface is None
    assert switch_state.effective_external_interface == "eth2"
    assert switch_state.interface_conflict is True
    overlaid = await service.overlay(snapshot, snapshot.gateway, snapshot.nodes, [], {})
    switch_edge = next(edge for edge in overlaid.edges if edge.id == uplink.id)
    assert switch_edge.target_handle == "sdex-eth2"


def test_shared_aggregate_keeps_rack_status_rules() -> None:
    nodes = {
        "up": _node("up"),
        "down": _node("down", ConnectionStatus.DISCONNECTED),
    }
    assert aggregate_topology_state(["up"], nodes).status == ConnectionStatus.CONNECTED
    assert aggregate_topology_state(["up", "down"], nodes).status == ConnectionStatus.DEGRADED
    assert aggregate_topology_state([], nodes).status == ConnectionStatus.UNKNOWN


def test_alarm_model_deduplicates_stable_ids_and_preserves_severity() -> None:
    duplicate = ActiveAlarm(
        id="partial_discovery",
        severity=AlarmSeverity.WARNING,
        title="Partial",
        description="One or more modules failed.",
    )
    assert deduplicate_alarms([duplicate, duplicate]) == [duplicate]

    snapshot = TopologySnapshot(
        gateway=_gateway(),
        partial=True,
        generated_at=NOW,
        module_results=[
            ModuleResult(module="fanuc", status=ModuleStatus.UNAVAILABLE),
            ModuleResult(module="opcua-client", status=ModuleStatus.FORBIDDEN),
        ],
    )
    alarms = build_active_alarms(snapshot, tls_verification_disabled=True)
    by_id = {alarm.id: alarm for alarm in alarms}
    assert set(by_id) == {
        "partial_discovery",
        "module_refresh_failed",
        "tls_verification_disabled",
    }
    assert len(alarms) == 3
    assert all(alarm.severity == AlarmSeverity.WARNING for alarm in alarms)


def test_restore_ids_are_optional_validated_and_conflict_safe(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True)
    element_id = "switch:00000000-0000-4000-8000-000000000901"
    link_id = "visual-link:00000000-0000-4000-8000-000000000902"
    with TestClient(create_app(settings)) as client:
        gateway_id = _refreshed(client)["gateway"]["id"]
        created = client.post(
            "/api/visual-elements",
            json={
                "id": element_id,
                "type": "switch",
                "name": "Restored Switch",
                "position": {"x": 20, "y": 30},
                "external_interface": "eth1",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["id"] == element_id
        duplicate = client.post(
            "/api/visual-elements",
            json={"id": element_id, "type": "switch", "position": {"x": 0, "y": 0}},
        )
        assert duplicate.status_code == 409
        linked = client.post(
            "/api/visual-links",
            json={
                "id": link_id,
                "source": element_id,
                "target": gateway_id,
                "external_interface": "eth1",
            },
        )
        assert linked.status_code == 201, linked.text
        assert linked.json()["id"] == link_id
