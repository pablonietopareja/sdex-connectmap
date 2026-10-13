from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime

from app.core.errors import ResourceNotFoundError, TopologyConflictError
from app.models.schemas import (
    AggregateSummary,
    AssignmentSource,
    ConnectionNode,
    ConnectionStatus,
    ConnectionType,
    EdgeRoute,
    EdgeRouteUpdate,
    InterfaceAssignment,
    Position,
    RackMembership,
    RackMemberUpdate,
    TopologyEdge,
    TopologySnapshot,
    VisualElement,
    VisualElementCreate,
    VisualElementType,
    VisualElementUpdate,
    VisualLink,
    VisualLinkCreate,
    VisualLinkUpdate,
    VisualTopologyState,
)
from app.persistence import Database

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _rack_dimensions(rows: int, columns: int) -> tuple[float, float]:
    width = 40.0 + columns * 330.0 + (columns - 1) * 16.0
    height = 64.0 + 16.0 + rows * 192.0 + (rows - 1) * 16.0 + 52.0
    return width, height


SWITCH_WIDTH = 310.0
SWITCH_HEIGHT = 228.0


def aggregate_topology_state(
    connection_ids: list[str],
    nodes: dict[str, ConnectionNode],
) -> AggregateSummary:
    counts: Counter[str] = Counter()
    for connection_id in dict.fromkeys(connection_ids):
        node = nodes.get(connection_id)
        if node is None:
            counts["missing"] += 1
            counts["unknown"] += 1
            continue
        if not node.enabled or node.status == ConnectionStatus.DISABLED:
            counts["disabled"] += 1
        elif node.status == ConnectionStatus.CONNECTED:
            counts["connected"] += 1
        elif node.status == ConnectionStatus.DISCONNECTED:
            counts["disconnected"] += 1
        elif node.status == ConnectionStatus.DEGRADED:
            counts["degraded"] += 1
        else:
            counts["unknown"] += 1

    total = len(dict.fromkeys(connection_ids))
    enabled = total - counts["disabled"]
    if total == 0:
        status = ConnectionStatus.UNKNOWN
    elif enabled == 0:
        status = ConnectionStatus.DISABLED
    elif counts["connected"] == enabled:
        status = ConnectionStatus.CONNECTED
    elif counts["disconnected"] == enabled:
        status = ConnectionStatus.DISCONNECTED
    elif counts["unknown"] == enabled:
        status = ConnectionStatus.UNKNOWN
    else:
        status = ConnectionStatus.DEGRADED
    return AggregateSummary(
        status=status,
        total=total,
        connected=counts["connected"],
        disconnected=counts["disconnected"],
        disabled=counts["disabled"],
        unknown=counts["unknown"],
        degraded=counts["degraded"],
        missing=counts["missing"],
        animated=counts["connected"] > 0,
    )


# Compatibility name retained for existing callers while Rack and Switch now
# share the same semantic aggregation function.
aggregate_connections = aggregate_topology_state


class VisualTopologyService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._mutation_lock = asyncio.Lock()

    async def state_for_snapshot(self, snapshot: TopologySnapshot) -> VisualTopologyState:
        state = await self.database.load_visual_topology()
        nodes = {node.id: node for node in snapshot.nodes}
        memberships = [
            membership.model_copy(
                update={
                    "connection": nodes.get(membership.connection_id),
                    "missing": membership.connection_id not in nodes,
                }
            )
            for membership in state.rack_memberships
        ]
        members_by_rack: dict[str, list[str]] = defaultdict(list)
        for membership in memberships:
            members_by_rack[membership.rack_id].append(membership.connection_id)
        incoming: dict[str, list[str]] = defaultdict(list)
        for link in state.links:
            incoming[link.target].append(link.source)

        def descendants(element_id: str, visiting: frozenset[str] = frozenset()) -> list[str]:
            if element_id in visiting:
                return []
            if element_id in nodes:
                return [element_id]
            if element_id.startswith("rack:"):
                return members_by_rack.get(element_id, [])
            if element_id.startswith("switch:"):
                result: list[str] = []
                for source in incoming.get(element_id, []):
                    result.extend(descendants(source, visiting | {element_id}))
                return result
            return []

        elements = []
        for element in state.elements:
            descendant_ids = (
                members_by_rack.get(element.id, [])
                if element.type == VisualElementType.RACK
                else descendants(element.id)
            )
            aggregate = aggregate_topology_state(descendant_ids, nodes)
            interface_names: set[str] = set()
            every_interface_resolved = bool(descendant_ids)
            for connection_id in dict.fromkeys(descendant_ids):
                node = nodes.get(connection_id)
                assignment = node.interface_assignment if node is not None else None
                if (
                    assignment is None
                    or not assignment.resolved
                    or assignment.interface_name is None
                ):
                    every_interface_resolved = False
                    continue
                interface_names.add(assignment.interface_name)
            derived_interface = (
                next(iter(interface_names))
                if every_interface_resolved and len(interface_names) == 1
                else None
            )
            interface_conflict = len(interface_names) > 1
            if element.external_interface is not None and any(
                name != element.external_interface for name in interface_names
            ):
                interface_conflict = True
            effective_interface = element.external_interface or derived_interface
            enriched = element.model_copy(
                update={
                    "aggregate": aggregate,
                    "derived_external_interface": derived_interface,
                    "effective_external_interface": effective_interface,
                    "interface_conflict": interface_conflict,
                }
            )
            elements.append(enriched)
            if element.type == VisualElementType.SWITCH and descendant_ids:
                logger.debug(
                    "Calculated Switch downstream aggregate",
                    extra={
                        "event": "switch_aggregate",
                        "element_id": element.id,
                        "status": str(aggregate.status),
                        "count": aggregate.total,
                        "interface_conflict": interface_conflict,
                    },
                )
        return state.model_copy(update={"elements": elements, "rack_memberships": memberships})

    async def overlay(
        self,
        snapshot: TopologySnapshot,
        gateway: ConnectionNode,
        nodes: list[ConnectionNode],
        base_edges: list[TopologyEdge],
        styles: dict,
    ) -> TopologySnapshot:
        state = await self.state_for_snapshot(snapshot.model_copy(update={"nodes": nodes}))
        nodes_by_id = {node.id: node for node in nodes}
        members = {membership.connection_id for membership in state.rack_memberships}
        linked_sources = {link.source for link in state.links}
        suppressed = set(state.unrouted_connection_ids)
        edges = [
            edge.model_copy(
                update={
                    "route": state.routes.get(edge.id),
                }
            )
            for edge in base_edges
            if edge.source not in members | linked_sources | suppressed
        ]
        elements = {element.id: element for element in state.elements}
        for link in state.links:
            source_node = nodes_by_id.get(link.source)
            if source_node is not None and (
                not source_node.enabled or source_node.status == ConnectionStatus.DISABLED
            ):
                continue
            source_exists = link.source in nodes_by_id or link.source in elements
            target_exists = link.target == gateway.id or link.target in elements
            if not source_exists or not target_exists:
                continue
            source_element = elements.get(link.source)
            aggregate = source_element.aggregate if source_element else None
            if source_element and source_element.type == VisualElementType.RACK:
                if aggregate is None or aggregate.total == 0:
                    continue
            effective_interface = link.external_interface
            if source_element is not None and source_element.effective_external_interface:
                effective_interface = source_element.effective_external_interface
            assignment = InterfaceAssignment(
                resolved=effective_interface is not None,
                interface_name=effective_interface,
                source=(
                    AssignmentSource.MANUAL_OVERRIDE
                    if effective_interface is not None
                    else AssignmentSource.UNRESOLVED
                ),
                reason=(
                    "The aggregate uplink uses its effective logical SDEX interface."
                    if effective_interface is not None
                    else "The visual topology link has no resolved SDEX interface."
                ),
            )
            target_handle = link.target_handle
            if link.target == gateway.id and effective_interface is not None:
                target_handle = f"sdex-{effective_interface}"
            edges.append(
                TopologyEdge(
                    id=link.id,
                    source=link.source,
                    target=link.target,
                    source_handle=link.source_handle,
                    target_handle=target_handle,
                    interface_assignment=assignment,
                    style=styles.get(link.id),
                    kind=("aggregate" if source_element is not None else "visual"),
                    route=state.routes.get(link.id),
                    aggregate=aggregate,
                )
            )
        edges.sort(key=lambda edge: edge.id)
        return snapshot.model_copy(
            update={
                "gateway": gateway,
                "nodes": nodes,
                "edges": edges,
                "visual_topology": state,
            }
        )

    async def create_element(self, payload: VisualElementCreate) -> VisualElement:
        async with self._mutation_lock:
            now = utc_now()
            element_id = payload.id or f"{payload.type}:{uuid.uuid4()}"
            state = await self.database.load_visual_topology()
            if any(element.id == element_id for element in state.elements):
                raise TopologyConflictError("That visual element id already exists.")
            if payload.type == VisualElementType.RACK:
                rows = payload.rows or 1
                columns = payload.columns or 3
                width, height = _rack_dimensions(rows, columns)
                name = payload.name or "New Rack"
                status_mode = "aggregate"
            else:
                rows = columns = None
                width, height = SWITCH_WIDTH, SWITCH_HEIGHT
                name = payload.name or "New Switch"
                status_mode = payload.status_mode
            element = VisualElement(
                id=element_id,
                type=payload.type,
                name=name,
                description=payload.description,
                position=payload.position,
                width=width,
                height=height,
                rows=rows,
                columns=columns,
                external_interface=payload.external_interface,
                status_mode=status_mode,
                schema_version=1,
                created_at=now,
                updated_at=now,
            )
            return await self.database.save_visual_element(element)

    async def update_element(
        self,
        element_id: str,
        payload: VisualElementUpdate,
        snapshot: TopologySnapshot,
    ) -> VisualElement:
        async with self._mutation_lock:
            return await self._update_element_locked(element_id, payload, snapshot)

    async def _update_element_locked(
        self,
        element_id: str,
        payload: VisualElementUpdate,
        snapshot: TopologySnapshot,
    ) -> VisualElement:
        state = await self.state_for_snapshot(snapshot)
        current = next((item for item in state.elements if item.id == element_id), None)
        if current is None:
            raise ResourceNotFoundError()
        updates = payload.model_dump(exclude_unset=True, exclude={"overflow_policy"})
        if current.type == VisualElementType.SWITCH and ({"rows", "columns"} & updates.keys()):
            raise TopologyConflictError("A Switch cannot define a rack matrix.")
        if current.type == VisualElementType.RACK and (
            ("rows" in updates and updates["rows"] is None)
            or ("columns" in updates and updates["columns"] is None)
        ):
            raise TopologyConflictError("A Rack must keep at least one row and one column.")
        rows = updates.get("rows", current.rows)
        columns = updates.get("columns", current.columns)
        memberships = [
            membership for membership in state.rack_memberships if membership.rack_id == element_id
        ]
        if "external_interface" in updates:
            requested_interface = updates["external_interface"]
            if memberships and requested_interface is None:
                raise TopologyConflictError("A Rack with members must keep one external interface.")
            node_by_id = {node.id: node for node in snapshot.nodes}
            incompatible = []
            for membership in memberships:
                member = node_by_id.get(membership.connection_id)
                assignment = member.interface_assignment if member else None
                if (
                    assignment is not None
                    and assignment.resolved
                    and assignment.interface_name != requested_interface
                ):
                    incompatible.append(membership.connection_id)
            if incompatible:
                raise TopologyConflictError(
                    "Existing members use a different SDEX interface.",
                    details={"incompatible_member_ids": incompatible},
                )
        overflow = [
            membership
            for membership in memberships
            if rows is not None
            and columns is not None
            and (membership.row >= rows or membership.column >= columns)
        ]
        if overflow and payload.overflow_policy == "reject":
            raise TopologyConflictError(
                "The requested rack matrix would evict existing members.",
                details={"overflow_member_ids": [item.connection_id for item in overflow]},
            )
        if current.type == VisualElementType.RACK and rows is not None and columns is not None:
            updates["width"], updates["height"] = _rack_dimensions(rows, columns)
        updates["updated_at"] = utc_now()
        updated = VisualElement.model_validate({**current.model_dump(), **updates})
        await self.database.update_visual_element(
            updated,
            eject_overflow=payload.overflow_policy == "eject",
        )
        return updated

    async def delete_element(
        self,
        element_id: str,
        snapshot: TopologySnapshot,
        *,
        eject_members: bool,
        leave_unrouted: bool = False,
    ) -> tuple[list[str], list[str]]:
        async with self._mutation_lock:
            return await self._delete_element_locked(
                element_id,
                snapshot,
                eject_members=eject_members,
                leave_unrouted=leave_unrouted,
            )

    async def _delete_element_locked(
        self,
        element_id: str,
        snapshot: TopologySnapshot,
        *,
        eject_members: bool,
        leave_unrouted: bool,
    ) -> tuple[list[str], list[str]]:
        state = await self.state_for_snapshot(snapshot)
        current = next((item for item in state.elements if item.id == element_id), None)
        if current is None:
            raise ResourceNotFoundError()
        members = [
            item.connection_id for item in state.rack_memberships if item.rack_id == element_id
        ]
        if members and not eject_members:
            raise TopologyConflictError(
                "The Rack contains members; explicit ejection is required.",
                details={"member_ids": members},
            )
        deleted, ejected, _links, unrouted = await self.database.delete_visual_element(
            element_id,
            gateway_id=snapshot.gateway.id,
            eject_members=eject_members,
            leave_unrouted=leave_unrouted,
        )
        if not deleted:
            raise ResourceNotFoundError()
        return ejected, unrouted

    async def put_member(
        self,
        rack_id: str,
        payload: RackMemberUpdate,
        snapshot: TopologySnapshot,
    ) -> RackMembership:
        async with self._mutation_lock:
            return await self._put_member_locked(rack_id, payload, snapshot)

    async def _put_member_locked(
        self,
        rack_id: str,
        payload: RackMemberUpdate,
        snapshot: TopologySnapshot,
    ) -> RackMembership:
        state = await self.state_for_snapshot(snapshot)
        rack = next(
            (
                item
                for item in state.elements
                if item.id == rack_id and item.type == VisualElementType.RACK
            ),
            None,
        )
        if rack is None:
            raise ResourceNotFoundError()
        node = next((item for item in snapshot.nodes if item.id == payload.connection_id), None)
        if node is None:
            raise ResourceNotFoundError()
        industrial_types = {
            ConnectionType.SIEMENS_S7_1200_1500,
            ConnectionType.SIEMENS_S7_300_400,
            ConnectionType.ROCKWELL_ALLEN_BRADLEY,
            ConnectionType.MODBUS,
            ConnectionType.SINUMERIK_840D,
            ConnectionType.FANUC_CNC,
        }
        if node.type not in industrial_types:
            raise TopologyConflictError(
                "Racks can contain only industrial PLC, CNC, and Modbus connections."
            )
        if payload.row >= (rack.rows or 0) or payload.column >= (rack.columns or 0):
            raise TopologyConflictError("The selected Rack slot is outside the configured matrix.")
        for membership in state.rack_memberships:
            if membership.connection_id == payload.connection_id and membership.rack_id != rack_id:
                raise TopologyConflictError("A connection can belong to only one Rack.")
            if (
                membership.rack_id == rack_id
                and membership.row == payload.row
                and membership.column == payload.column
                and membership.connection_id != payload.connection_id
            ):
                raise TopologyConflictError("The selected Rack slot is already occupied.")
        if any(link.source == payload.connection_id for link in state.links):
            raise TopologyConflictError(
                "Remove the connection's visual uplink before placing it in a Rack."
            )
        assignment = node.interface_assignment
        resolved_interface = (
            assignment.interface_name if assignment is not None and assignment.resolved else None
        )
        rack_interface = rack.external_interface
        if rack_interface is None and resolved_interface is not None:
            rack_interface = resolved_interface
        if resolved_interface is not None and rack_interface != resolved_interface:
            raise TopologyConflictError(
                "The connection and Rack use different SDEX interfaces.",
                details={
                    "connection_interface": resolved_interface,
                    "rack_interface": rack_interface,
                },
            )
        unresolved_confirmed = resolved_interface is None
        if unresolved_confirmed and (
            rack_interface is None or not payload.allow_unresolved_interface
        ):
            raise TopologyConflictError(
                "The connection interface is unresolved; select a Rack interface and confirm it."
            )
        try:
            return await self.database.save_rack_membership(
                rack_id,
                node,
                payload.row,
                payload.column,
                unresolved_interface_confirmed=unresolved_confirmed,
                connection_interface=resolved_interface,
                validate_interface=True,
                allow_unresolved_interface=payload.allow_unresolved_interface,
            )
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                raise TopologyConflictError(
                    "The Rack membership conflicts with existing data."
                ) from exc
            raise

    async def remove_member(self, rack_id: str, connection_id: str) -> None:
        async with self._mutation_lock:
            if not await self.database.delete_rack_membership(rack_id, connection_id):
                raise ResourceNotFoundError()

    @staticmethod
    def _endpoint_ids(snapshot: TopologySnapshot, state: VisualTopologyState) -> set[str]:
        return {
            snapshot.gateway.id,
            *(node.id for node in snapshot.nodes),
            *(element.id for element in state.elements),
        }

    @staticmethod
    def _would_cycle(links: list[VisualLink], source: str, target: str) -> bool:
        outgoing = {link.source: link.target for link in links}
        outgoing[source] = target
        current = target
        visited: set[str] = set()
        while current in outgoing:
            if current == source:
                return True
            if current in visited:
                return True
            visited.add(current)
            current = outgoing[current]
        return False

    @staticmethod
    def _source_interface(
        source: str,
        snapshot: TopologySnapshot,
        state: VisualTopologyState,
    ) -> str | None:
        node = next((item for item in snapshot.nodes if item.id == source), None)
        if node and node.interface_assignment and node.interface_assignment.resolved:
            return node.interface_assignment.interface_name
        element = next((item for item in state.elements if item.id == source), None)
        return (
            element.effective_external_interface or element.external_interface if element else None
        )

    @staticmethod
    def _normalize_handle_placeholder(handle: str | None, link_id: str) -> str | None:
        if handle in {"left:new", "right:new"}:
            return f"{handle.split(':', 1)[0]}:{link_id}"
        return handle

    async def create_link(
        self,
        payload: VisualLinkCreate,
        snapshot: TopologySnapshot,
    ) -> VisualLink:
        async with self._mutation_lock:
            state = await self.state_for_snapshot(snapshot)
            return await self._save_link(None, payload, snapshot, state)

    async def update_link(
        self,
        link_id: str,
        payload: VisualLinkUpdate,
        snapshot: TopologySnapshot,
    ) -> VisualLink:
        async with self._mutation_lock:
            return await self._update_link_locked(link_id, payload, snapshot)

    async def _update_link_locked(
        self,
        link_id: str,
        payload: VisualLinkUpdate,
        snapshot: TopologySnapshot,
    ) -> VisualLink:
        state = await self.state_for_snapshot(snapshot)
        current = next((item for item in state.links if item.id == link_id), None)
        if current is None:
            raise ResourceNotFoundError()
        merged = VisualLinkCreate(
            source=current.source,
            target=payload.target or current.target,
            source_handle=(
                payload.source_handle
                if "source_handle" in payload.model_fields_set
                else current.source_handle
            ),
            target_handle=(
                payload.target_handle
                if "target_handle" in payload.model_fields_set
                else current.target_handle
            ),
            external_interface=(
                payload.external_interface
                if "external_interface" in payload.model_fields_set
                else current.external_interface
            ),
            allow_unresolved_interface=payload.allow_unresolved_interface,
        )
        return await self._save_link(current, merged, snapshot, state)

    async def _save_link(
        self,
        current: VisualLink | None,
        payload: VisualLinkCreate,
        snapshot: TopologySnapshot,
        state: VisualTopologyState,
    ) -> VisualLink:
        if payload.source == payload.target:
            raise TopologyConflictError("A visual link cannot connect an element to itself.")
        endpoint_ids = self._endpoint_ids(snapshot, state)
        if payload.source not in endpoint_ids or payload.target not in endpoint_ids:
            raise ResourceNotFoundError()
        if payload.source == snapshot.gateway.id or payload.target in {
            node.id for node in snapshot.nodes
        }:
            raise TopologyConflictError("Visual links must be oriented toward SDEX.")
        relevant_links = [link for link in state.links if current is None or link.id != current.id]
        if any(
            {link.source, link.target} == {payload.source, payload.target}
            for link in relevant_links
        ):
            raise TopologyConflictError("That visual link already exists.")
        if any(link.source == payload.source for link in relevant_links):
            raise TopologyConflictError("The source already has a visual uplink.")
        if self._would_cycle(relevant_links, payload.source, payload.target):
            raise TopologyConflictError("The visual link would create a cycle.")
        if any(member.connection_id == payload.source for member in state.rack_memberships):
            raise TopologyConflictError("A Rack member cannot also have an external visual link.")

        source_interface = self._source_interface(payload.source, snapshot, state)
        selected_interface = payload.external_interface or source_interface
        if source_interface is not None and selected_interface != source_interface:
            raise TopologyConflictError("The visual link conflicts with the source interface.")
        unresolved_confirmed = source_interface is None
        if unresolved_confirmed and (
            selected_interface is None or not payload.allow_unresolved_interface
        ):
            raise TopologyConflictError(
                "The source interface is unresolved; select and explicitly confirm eth1 or eth2."
            )
        target_element = next((item for item in state.elements if item.id == payload.target), None)
        if target_element is not None:
            if target_element.type != VisualElementType.SWITCH:
                raise TopologyConflictError("Only a Switch or SDEX can be an uplink target.")
        now = utc_now()
        link_id = current.id if current else payload.id or f"visual-link:{uuid.uuid4()}"
        if current is None and any(link.id == link_id for link in state.links):
            raise TopologyConflictError("That visual link id already exists.")
        source_handle = payload.source_handle
        target_handle = payload.target_handle
        source_element = next((item for item in state.elements if item.id == payload.source), None)
        if source_element:
            if source_element.type == VisualElementType.SWITCH:
                if source_handle and not source_handle.startswith(("left", "right")):
                    raise TopologyConflictError("Switch handles must be on the left or right side.")
                source_handle = source_handle or f"right:{link_id}"
            elif source_handle not in {None, "rack-left", "rack-right"}:
                raise TopologyConflictError("Rack uplinks must use the left or right Rack handle.")
            else:
                source_handle = source_handle or "rack-right"
        if target_element is not None:
            if target_handle and not target_handle.startswith(("left", "right")):
                raise TopologyConflictError("Switch handles must be on the left or right side.")
            target_handle = target_handle or f"left:{link_id}"
        source_handle = self._normalize_handle_placeholder(source_handle, link_id)
        target_handle = self._normalize_handle_placeholder(target_handle, link_id)
        link = VisualLink(
            id=link_id,
            source=payload.source,
            target=payload.target,
            source_handle=source_handle,
            target_handle=target_handle,
            external_interface=selected_interface,
            unresolved_interface_confirmed=unresolved_confirmed,
            schema_version=1,
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        return await self.database.save_visual_link(link)

    async def delete_link(self, link_id: str, *, leave_unrouted: bool) -> None:
        async with self._mutation_lock:
            if not await self.database.delete_visual_link(link_id, leave_unrouted=leave_unrouted):
                raise ResourceNotFoundError()

    async def save_route(
        self,
        edge_id: str,
        payload: EdgeRouteUpdate,
        snapshot: TopologySnapshot,
    ) -> EdgeRoute | None:
        async with self._mutation_lock:
            if edge_id not in {edge.id for edge in snapshot.edges}:
                raise ResourceNotFoundError()
            return await self.database.save_edge_route(edge_id, payload)

    async def reset_route(self, edge_id: str, snapshot: TopologySnapshot) -> None:
        async with self._mutation_lock:
            known_ids = {edge.id for edge in snapshot.edges}
            known_ids.update((await self.database.load_visual_topology()).routes)
            if edge_id not in known_ids:
                raise ResourceNotFoundError()
            await self.database.delete_edge_route(edge_id)

    async def ensure_editor_preview(self, snapshot: TopologySnapshot) -> None:
        async with self._mutation_lock:
            await self._ensure_editor_preview_locked(snapshot)

    async def _ensure_editor_preview_locked(self, snapshot: TopologySnapshot) -> None:
        state = await self.database.load_visual_topology()
        if (
            state.elements
            or state.rack_memberships
            or state.links
            or state.routes
            or state.unrouted_connection_ids
        ):
            return
        nodes = {node.display_name: node for node in snapshot.nodes}
        required = {"Packaging PLC", "Legacy Line PLC", "Assembly ControlLogix"}
        if not required <= nodes.keys():
            return
        now = utc_now()
        rack_id = "rack:00000000-0000-4000-8000-000000000001"
        switch_id = "switch:00000000-0000-4000-8000-000000000002"
        rack = VisualElement(
            id=rack_id,
            type="rack",
            name="Production Rack",
            position=Position(x=-1480, y=-120),
            width=_rack_dimensions(1, 3)[0],
            height=_rack_dimensions(1, 3)[1],
            rows=1,
            columns=3,
            external_interface="eth1",
            status_mode="aggregate",
            created_at=now,
            updated_at=now,
        )
        switch = VisualElement(
            id=switch_id,
            type="switch",
            name="Line Switch",
            position=Position(x=760, y=-330),
            width=SWITCH_WIDTH,
            height=SWITCH_HEIGHT,
            external_interface="eth1",
            status_mode="aggregate",
            created_at=now,
            updated_at=now,
        )
        seed_memberships = [
            (rack_id, nodes[name], 0, column, False)
            for column, name in enumerate(("Packaging PLC", "Legacy Line PLC"))
        ]
        rack_link = VisualLink(
            id="visual-link:00000000-0000-4000-8000-000000000011",
            source=rack_id,
            target=snapshot.gateway.id,
            source_handle="rack-right",
            target_handle="sdex-eth1",
            external_interface="eth1",
            created_at=now,
            updated_at=now,
        )
        device_link = VisualLink(
            id="visual-link:00000000-0000-4000-8000-000000000012",
            source=nodes["Assembly ControlLogix"].id,
            target=switch_id,
            target_handle="left:visual-link:00000000-0000-4000-8000-000000000012",
            external_interface="eth1",
            created_at=now,
            updated_at=now,
        )
        switch_link = VisualLink(
            id="visual-link:00000000-0000-4000-8000-000000000013",
            source=switch_id,
            target=snapshot.gateway.id,
            source_handle="right:visual-link:00000000-0000-4000-8000-000000000013",
            target_handle="sdex-eth1",
            external_interface="eth1",
            created_at=now,
            updated_at=now,
        )
        await self.database.seed_visual_topology(
            [rack, switch],
            seed_memberships,
            [rack_link, device_link, switch_link],
            [
                (
                    rack_link.id,
                    EdgeRouteUpdate(
                        routing_mode="manual",
                        waypoints=[{"id": "rack-bend", "x": -270, "y": -170, "kind": "free"}],
                    ),
                ),
                (
                    switch_link.id,
                    EdgeRouteUpdate(
                        routing_mode="orthogonal",
                        waypoints=[
                            {
                                "id": "switch-corner",
                                "x": 310,
                                "y": 280,
                                "kind": "corner",
                            }
                        ],
                    ),
                ),
            ],
        )
