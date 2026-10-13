from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.errors import ResourceNotFoundError, TopologyConflictError
from app.core.security import CredentialCipher
from app.models.schemas import (
    AssignmentSource,
    ConnectionNode,
    ConnectionStatus,
    ConnectionType,
    EdgeRouteUpdate,
    InterfaceAssignment,
    LayoutPosition,
    Position,
    RackMemberUpdate,
    TopologySnapshot,
    VisualElement,
    VisualElementUpdate,
    VisualLink,
    VisualLinkCreate,
)
from app.persistence import Database
from app.services.visual_topology import VisualTopologyService, aggregate_connections

NOW = datetime(2026, 7, 31, tzinfo=UTC)


def node(node_id: str, status: ConnectionStatus = ConnectionStatus.CONNECTED) -> ConnectionNode:
    return ConnectionNode(
        id=node_id,
        type=ConnectionType.MODBUS,
        display_name=node_id,
        address="192.0.2.20",
        enabled=True,
        licensed=True,
        status=status,
        source_module="modbus",
        icon="/icons/Modbus.svg",
    )


def gateway() -> ConnectionNode:
    return ConnectionNode(
        id="sdex_gateway:sdex",
        type=ConnectionType.SDEX_GATEWAY,
        display_name="SDEX",
        enabled=True,
        status=ConnectionStatus.CONNECTED,
        source_module="core",
        icon="/icons/SDEX.svg",
    )


def resolved_node(node_id: str, interface_name: str = "eth1") -> ConnectionNode:
    return node(node_id).model_copy(
        update={
            "interface_assignment": InterfaceAssignment(
                resolved=True,
                interface_name=interface_name,
                source=AssignmentSource.SUBNET,
                reason="test",
            )
        }
    )


def rack() -> VisualElement:
    return VisualElement(
        id="rack:00000000-0000-4000-8000-000000000001",
        type="rack",
        name="Rack",
        position=Position(x=10, y=20),
        width=1084,
        height=354,
        rows=1,
        columns=3,
        external_interface="eth1",
        created_at=NOW,
        updated_at=NOW,
    )


def visual_switch(suffix: int, *, external_interface: str | None = "eth1") -> VisualElement:
    return VisualElement(
        id=f"switch:00000000-0000-4000-8000-{suffix:012d}",
        type="switch",
        name=f"Switch {suffix}",
        position=Position(x=500 + suffix, y=20),
        width=310,
        height=228,
        external_interface=external_interface,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_visual_state_routes_and_element_layout_survive_restart(tmp_path) -> None:
    key = Fernet.generate_key()
    path = tmp_path / "visual.db"
    database = Database(path, CredentialCipher(key))
    await database.initialize()
    element = rack()
    connection = node("modbus:meter")
    await database.save_visual_element(element)
    await database.save_rack_membership(
        element.id,
        connection,
        0,
        0,
        unresolved_interface_confirmed=False,
    )
    link = VisualLink(
        id="visual-link:00000000-0000-4000-8000-000000000011",
        source=element.id,
        target="sdex_gateway:sdex",
        external_interface="eth1",
        created_at=NOW,
        updated_at=NOW,
    )
    await database.save_visual_link(link)
    await database.save_edge_route(
        link.id,
        EdgeRouteUpdate(
            routing_mode="manual",
            waypoints=[{"id": "bend", "x": 50, "y": 60, "kind": "free"}],
        ),
    )
    await database.save_layout([LayoutPosition(node_id=element.id, x=125, y=-75)], None)

    restarted = Database(path, CredentialCipher(key))
    await restarted.initialize()
    state = await restarted.load_visual_topology()
    assert state.elements[0].position == Position(x=125, y=-75)
    assert state.rack_memberships[0].cached_display_name == "modbus:meter"
    assert state.links[0].id == link.id
    assert state.routes[link.id].waypoints[0].model_dump() == {
        "x": 50.0,
        "y": 60.0,
        "id": "bend",
        "kind": "free",
        "order": 0,
    }
    assert (await restarted.load_layout()).positions[element.id] == Position(x=125, y=-75)


@pytest.mark.asyncio
async def test_missing_connection_keeps_membership_without_polluting_source_summary(
    database,
) -> None:
    element = rack()
    connection = node("modbus:missing")
    await database.save_visual_element(element)
    await database.save_rack_membership(
        element.id,
        connection,
        0,
        0,
        unresolved_interface_confirmed=False,
    )
    snapshot = TopologySnapshot(gateway=gateway(), nodes=[])
    state = await VisualTopologyService(database).state_for_snapshot(snapshot)
    assert snapshot.nodes == []
    assert state.rack_memberships[0].missing is True
    assert state.rack_memberships[0].connection is None
    assert state.elements[0].aggregate is not None
    assert state.elements[0].aggregate.missing == 1
    assert state.elements[0].aggregate.status == ConnectionStatus.UNKNOWN


@pytest.mark.asyncio
async def test_unresolved_industrial_member_requires_explicit_interface_confirmation(
    database,
) -> None:
    element = rack()
    connection = node("modbus:unresolved")
    await database.save_visual_element(element)
    snapshot = TopologySnapshot(gateway=gateway(), nodes=[connection])
    service = VisualTopologyService(database)
    with pytest.raises(TopologyConflictError, match="interface is unresolved"):
        await service.put_member(
            element.id,
            RackMemberUpdate(connection_id=connection.id, row=0, column=0),
            snapshot,
        )
    membership = await service.put_member(
        element.id,
        RackMemberUpdate(
            connection_id=connection.id,
            row=0,
            column=0,
            allow_unresolved_interface=True,
        ),
        snapshot,
    )
    assert membership.unresolved_interface_confirmed is True


def test_aggregate_status_rules_do_not_duplicate_member_ids() -> None:
    nodes = {
        "connected": node("connected", ConnectionStatus.CONNECTED),
        "down": node("down", ConnectionStatus.DISCONNECTED),
    }
    connected = aggregate_connections(["connected", "connected"], nodes)
    mixed = aggregate_connections(["connected", "down"], nodes)
    missing = aggregate_connections(["gone"], nodes)
    empty = aggregate_connections([], nodes)
    assert connected.total == 1 and connected.status == ConnectionStatus.CONNECTED
    assert mixed.status == ConnectionStatus.DEGRADED and mixed.animated is True
    assert missing.status == ConnectionStatus.UNKNOWN and missing.missing == 1
    assert empty.status == ConnectionStatus.UNKNOWN


def test_waypoints_reject_non_finite_or_excessive_coordinates() -> None:
    with pytest.raises(ValidationError):
        EdgeRouteUpdate(
            routing_mode="manual",
            waypoints=[{"id": "bad", "x": float("nan"), "y": 0}],
        )
    with pytest.raises(ValidationError):
        EdgeRouteUpdate(
            routing_mode="manual",
            waypoints=[{"id": "bad", "x": 1_000_001, "y": 0}],
        )


@pytest.mark.asyncio
async def test_schema_v3_adds_visual_tables_without_losing_existing_rows(tmp_path) -> None:
    path = tmp_path / "v3.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES (1, 3, 'legacy');
            CREATE TABLE node_layout (
                node_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO node_layout VALUES ('modbus:legacy', 12, 34, 'legacy');
            """
        )
    database = Database(path, CredentialCipher(Fernet.generate_key()))
    await database.initialize()
    assert await database.schema_version() == 5
    assert (await database.load_layout()).positions["modbus:legacy"] == Position(x=12, y=34)
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "topology_element",
        "rack_membership",
        "topology_link",
        "edge_route",
        "edge_waypoint",
    } <= tables


@pytest.mark.asyncio
async def test_schema_v4_failure_rolls_back_version_and_tables(tmp_path, monkeypatch) -> None:
    path = tmp_path / "v4-rollback.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES (1, 3, 'legacy');
            """
        )
    database = Database(path, CredentialCipher(Fernet.generate_key()))

    def fail_v4(connection):
        connection.execute("CREATE TABLE v4_probe(value TEXT)")
        raise RuntimeError("injected v4 migration failure")

    monkeypatch.setattr(database, "_create_version_four_tables", fail_v4)
    with pytest.raises(RuntimeError, match="injected v4 migration failure"):
        await database.initialize()
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()[
                0
            ]
            == 3
        )
        assert (
            connection.execute("SELECT 1 FROM sqlite_master WHERE name='v4_probe'").fetchone()
            is None
        )


@pytest.mark.asyncio
async def test_rack_resize_eject_rolls_back_and_places_cards_without_overlap(database) -> None:
    element = rack()
    connection = resolved_node("modbus:ejected")
    blocking_switch = visual_switch(90).model_copy(
        update={"position": Position(x=444, y=20), "width": 310, "height": 228}
    )
    await database.save_visual_element(element)
    await database.save_visual_element(blocking_switch)
    await database.save_rack_membership(
        element.id,
        connection,
        0,
        2,
        unresolved_interface_confirmed=False,
    )
    service = VisualTopologyService(database)
    snapshot = TopologySnapshot(gateway=gateway(), nodes=[connection])
    with sqlite3.connect(database.path) as sql:
        sql.execute(
            """
            CREATE TRIGGER abort_rack_resize
            BEFORE UPDATE ON topology_element
            WHEN NEW.element_id = 'rack:00000000-0000-4000-8000-000000000001'
            BEGIN
                SELECT RAISE(ABORT, 'forced rack resize failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced rack resize failure"):
        await service.update_element(
            element.id,
            VisualElementUpdate(columns=1, overflow_policy="eject"),
            snapshot,
        )
    failed_state = await database.load_visual_topology()
    assert failed_state.elements[0].columns == 3
    assert [item.connection_id for item in failed_state.rack_memberships] == [connection.id]
    assert connection.id not in (await database.load_layout()).positions

    with sqlite3.connect(database.path) as sql:
        sql.execute("DROP TRIGGER abort_rack_resize")
    updated = await service.update_element(
        element.id,
        VisualElementUpdate(columns=1, overflow_policy="eject"),
        snapshot,
    )
    assert updated.columns == 1
    final_state = await database.load_visual_topology()
    assert final_state.rack_memberships == []
    ejected = (await database.load_layout()).positions[connection.id]
    assert ejected.x == updated.position.x + updated.width + 64
    assert ejected.y >= blocking_switch.position.y + blocking_switch.height + 18


@pytest.mark.asyncio
async def test_interface_adoption_rolls_back_with_membership_or_link(database) -> None:
    element = rack().model_copy(update={"external_interface": None})
    connection = resolved_node("modbus:atomic-interface")
    await database.save_visual_element(element)
    service = VisualTopologyService(database)
    snapshot = TopologySnapshot(gateway=gateway(), nodes=[connection])
    with sqlite3.connect(database.path) as sql:
        sql.execute(
            """
            CREATE TRIGGER abort_membership
            BEFORE INSERT ON rack_membership
            BEGIN SELECT RAISE(ABORT, 'forced membership failure'); END
            """
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced membership failure"):
        await service.put_member(
            element.id,
            RackMemberUpdate(connection_id=connection.id, row=0, column=0),
            snapshot,
        )
    state = await database.load_visual_topology()
    assert state.elements[0].external_interface is None
    assert state.rack_memberships == []

    with sqlite3.connect(database.path) as sql:
        sql.execute("DROP TRIGGER abort_membership")
    target = visual_switch(91, external_interface=None)
    await database.save_visual_element(target)
    with sqlite3.connect(database.path) as sql:
        sql.execute(
            """
            CREATE TRIGGER abort_visual_link
            BEFORE INSERT ON topology_link
            BEGIN SELECT RAISE(ABORT, 'forced link failure'); END
            """
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced link failure"):
        await service.create_link(
            VisualLinkCreate(source=connection.id, target=target.id),
            snapshot,
        )
    state = await database.load_visual_topology()
    saved_target = next(item for item in state.elements if item.id == target.id)
    assert saved_target.external_interface is None
    assert state.links == []


@pytest.mark.asyncio
async def test_concurrent_membership_and_link_are_mutually_exclusive(
    database,
    monkeypatch,
) -> None:
    element = rack()
    target = visual_switch(92)
    connection = resolved_node("modbus:race")
    await database.save_visual_element(element)
    await database.save_visual_element(target)
    snapshot = TopologySnapshot(gateway=gateway(), nodes=[connection])
    frozen = await database.load_visual_topology()
    services = [VisualTopologyService(database), VisualTopologyService(database)]
    arrived = 0
    release = asyncio.Event()

    async def stale_state(_snapshot):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1)
        return frozen.model_copy(deep=True)

    for service in services:
        monkeypatch.setattr(service, "state_for_snapshot", stale_state)
    results = await asyncio.gather(
        services[0].put_member(
            element.id,
            RackMemberUpdate(connection_id=connection.id, row=0, column=0),
            snapshot,
        ),
        services[1].create_link(
            VisualLinkCreate(source=connection.id, target=target.id),
            snapshot,
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, TopologyConflictError) for result in results) == 1
    state = await database.load_visual_topology()
    assert bool(state.rack_memberships) != bool(state.links)


@pytest.mark.asyncio
async def test_concurrent_uplinks_from_one_source_have_one_winner(
    database,
    monkeypatch,
) -> None:
    source, first, second = (visual_switch(index) for index in (93, 94, 95))
    for element in (source, first, second):
        await database.save_visual_element(element)
    snapshot = TopologySnapshot(gateway=gateway(), nodes=[])
    frozen = await database.load_visual_topology()
    services = [VisualTopologyService(database), VisualTopologyService(database)]
    arrived = 0
    release = asyncio.Event()

    async def stale_state(_snapshot):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1)
        return frozen.model_copy(deep=True)

    for service in services:
        monkeypatch.setattr(service, "state_for_snapshot", stale_state)
    results = await asyncio.gather(
        services[0].create_link(VisualLinkCreate(source=source.id, target=first.id), snapshot),
        services[1].create_link(VisualLinkCreate(source=source.id, target=second.id), snapshot),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, TopologyConflictError) for result in results) == 1
    state = await database.load_visual_topology()
    assert len([link for link in state.links if link.source == source.id]) == 1


@pytest.mark.asyncio
async def test_visual_link_route_cannot_be_persisted_after_link_disappears(database) -> None:
    edge_id = "visual-link:00000000-0000-4000-8000-000000000099"
    update = EdgeRouteUpdate(
        routing_mode="manual",
        waypoints=[{"id": "stale", "x": 10, "y": 20}],
    )
    with pytest.raises(ResourceNotFoundError):
        await database.save_edge_route(edge_id, update)
    assert edge_id not in (await database.load_visual_topology()).routes

    direct_edge_id = "sdex-to-modbus:still-valid"
    saved = await database.save_edge_route(direct_edge_id, update)
    assert saved is not None and saved.edge_id == direct_edge_id


@pytest.mark.asyncio
async def test_loading_repairs_legacy_new_handle_placeholders(database) -> None:
    source = visual_switch(96)
    target = visual_switch(97)
    await database.save_visual_element(source)
    await database.save_visual_element(target)
    link = VisualLink(
        id="visual-link:00000000-0000-4000-8000-000000000096",
        source=source.id,
        target=target.id,
        source_handle="right:original",
        target_handle="left:original",
        external_interface="eth1",
        created_at=NOW,
        updated_at=NOW,
    )
    await database.save_visual_link(link)
    with sqlite3.connect(database.path) as sql:
        sql.execute(
            """
            UPDATE topology_link SET source_handle='right:new', target_handle='left:new'
            WHERE link_id=?
            """,
            (link.id,),
        )
    repaired = (await database.load_visual_topology()).links[0]
    assert repaired.source_handle == f"right:{link.id}"
    assert repaired.target_handle == f"left:{link.id}"


@pytest.mark.asyncio
async def test_editor_preview_seed_rolls_back_all_rows_and_can_retry(database) -> None:
    names = ("Packaging PLC", "Legacy Line PLC", "Assembly ControlLogix")
    nodes = [
        resolved_node(f"modbus:seed-{index}").model_copy(update={"display_name": name})
        for index, name in enumerate(names)
    ]
    snapshot = TopologySnapshot(gateway=gateway(), nodes=nodes)
    service = VisualTopologyService(database)
    with sqlite3.connect(database.path) as sql:
        sql.execute(
            """
            CREATE TRIGGER abort_editor_seed
            BEFORE INSERT ON topology_link
            WHEN NEW.link_id = 'visual-link:00000000-0000-4000-8000-000000000012'
            BEGIN SELECT RAISE(ABORT, 'forced editor seed failure'); END
            """
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced editor seed failure"):
        await service.ensure_editor_preview(snapshot)
    with sqlite3.connect(database.path) as sql:
        counts = sql.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM topology_element),
                (SELECT COUNT(*) FROM rack_membership),
                (SELECT COUNT(*) FROM topology_link),
                (SELECT COUNT(*) FROM edge_route),
                (SELECT COUNT(*) FROM edge_waypoint),
                (SELECT COUNT(*) FROM visual_route_suppression)
            """
        ).fetchone()
        assert counts == (0, 0, 0, 0, 0, 0)
        sql.execute("DROP TRIGGER abort_editor_seed")

    await service.ensure_editor_preview(snapshot)
    state = await database.load_visual_topology()
    assert len(state.elements) == 2
    assert len(state.rack_memberships) == 2
    assert len(state.links) == 3
    assert len(state.routes) == 2
