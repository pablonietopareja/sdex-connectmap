from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import __version__
from app.core.errors import (
    ConfigurationError,
    NotConfiguredError,
    ResourceNotFoundError,
    TopologyConflictError,
)
from app.models.schemas import (
    ConfigStatus,
    ConfigTestRequest,
    ConfigTestResponse,
    ConfigUpdateRequest,
    ConnectionInterfaceOverride,
    ConnectionProfile,
    DeviceVisualRouting,
    DeviceVisualRoutingUpdate,
    DisplaySettings,
    EdgeRoute,
    EdgeRouteUpdate,
    EdgeVisualStyle,
    EdgeVisualStyleUpdate,
    HealthResponse,
    InterfaceOverrideUpdate,
    LayoutUpdate,
    RackMembership,
    RackMemberUpdate,
    SettingsUpdate,
    TopologySnapshot,
    VisualElement,
    VisualElementCreate,
    VisualElementUpdate,
    VisualLink,
    VisualLinkCreate,
    VisualLinkUpdate,
    VisualTopologyState,
)
from app.services.discovery import normalize_system
from app.services.runtime import AppRuntime
from app.services.sdex_client import SDEXClient

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def runtime_from_request(request: Request) -> AppRuntime:
    return request.app.state.runtime


RuntimeDependency = Annotated[AppRuntime, Depends(runtime_from_request)]
EdgeId = Annotated[
    str,
    Path(
        min_length=9,
        max_length=320,
        pattern=r"^(?:sdex-to-[A-Za-z0-9_.:-]+|visual-link:[A-Za-z0-9_.:-]+)$",
    ),
]
VisualElementId = Annotated[
    str,
    Path(
        min_length=8,
        max_length=80,
        pattern=r"^(?:rack|switch):[0-9a-f-]{32,36}$",
    ),
]
VisualLinkId = Annotated[
    str,
    Path(
        min_length=13,
        max_length=80,
        pattern=r"^visual-link:[0-9a-f-]{32,36}$",
    ),
]
ConnectionId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=300,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
]


def _client_key(request: Request, operation: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{operation}:{host}"


async def config_status(runtime: AppRuntime) -> ConfigStatus:
    if runtime.settings.mock_mode:
        return ConfigStatus(
            configured=True,
            source="mock",
            mock_mode=True,
            verify_tls=True,
            password_configured=False,
        )
    profile = await runtime.discovery.client_manager.effective_profile()
    if profile is None:
        return ConfigStatus(
            configured=False,
            source="none",
            verify_tls=True,
            timeout_seconds=runtime.settings.request_timeout_seconds,
        )
    return ConfigStatus(
        configured=True,
        source=profile.source,
        base_url=profile.base_url,
        username=profile.username,
        verify_tls=profile.verify_tls,
        timeout_seconds=profile.timeout_seconds,
        password_configured=True,
        mock_mode=False,
        tls_warning=not profile.verify_tls,
    )


async def _password_for_test(
    runtime: AppRuntime,
    payload: ConfigTestRequest,
) -> str:
    if payload.password is not None:
        return payload.password.get_secret_value()
    existing = await runtime.discovery.client_manager.effective_profile()
    if (
        existing is None
        or existing.base_url != payload.base_url
        or existing.username != payload.username
    ):
        raise ConfigurationError(
            "Password is required when testing a different SDEX URL or username."
        )
    return existing.password.get_secret_value()


@router.get("/health", response_model=HealthResponse)
async def health(runtime: RuntimeDependency) -> HealthResponse:
    internal_error = False
    try:
        database_ok = await runtime.database.ping()
    except Exception:
        database_ok = False
        internal_error = True
    try:
        configured = await runtime.discovery.client_manager.configured()
    except Exception:
        configured = False
        internal_error = True
    try:
        snapshot = await runtime.database.load_snapshot()
    except Exception:
        snapshot = None
        internal_error = True
    scheduler_running = runtime.scheduler.running
    if internal_error or not database_ok or not scheduler_running:
        status = "degraded"
    elif not configured:
        status = "unconfigured"
    elif snapshot is not None and snapshot.stale:
        status = "degraded"
    else:
        status = "healthy"
    return HealthResponse(
        status=status,
        database="ok" if database_ok else "error",
        scheduler="running" if scheduler_running else "stopped",
        configured=configured,
        mock_mode=runtime.settings.mock_mode,
        refresh_in_progress=runtime.discovery.refresh_in_progress,
        last_successful_refresh=(
            snapshot.last_successful_refresh if snapshot is not None else None
        ),
        version=__version__,
    )


@router.get("/config/status", response_model=ConfigStatus)
async def get_config_status(runtime: RuntimeDependency) -> ConfigStatus:
    return await config_status(runtime)


@router.post("/config/test", response_model=ConfigTestResponse)
async def test_config(
    payload: ConfigTestRequest,
    request: Request,
    runtime: RuntimeDependency,
) -> ConfigTestResponse:
    await runtime.rate_limiter.check(
        _client_key(request, "config-test"),
        limit=10,
        window_seconds=60,
    )
    if runtime.settings.mock_mode:
        client = await runtime.discovery.client_manager.get()
        return ConfigTestResponse(system=normalize_system(await client.get_system()))
    password = await _password_for_test(runtime, payload)
    profile = ConnectionProfile(
        base_url=payload.base_url,
        username=payload.username,
        password=password,
        verify_tls=payload.verify_tls,
        timeout_seconds=payload.timeout_seconds,
        source="database",
    )
    client = SDEXClient(profile)
    try:
        system_payload = await client.get_system()
        system = normalize_system(system_payload)
    finally:
        await client.close()
    return ConfigTestResponse(system=system)


@router.put("/config", response_model=ConfigStatus)
async def save_config(
    payload: ConfigUpdateRequest,
    request: Request,
    runtime: RuntimeDependency,
) -> ConfigStatus:
    await runtime.rate_limiter.check(
        _client_key(request, "config-save"),
        limit=10,
        window_seconds=60,
    )
    existing = await runtime.discovery.client_manager.effective_profile()
    if payload.password is None:
        if (
            existing is None
            or existing.base_url != payload.base_url
            or existing.username != payload.username
        ):
            raise ConfigurationError(
                "Password is required when saving a different SDEX URL or username."
            )
        password = existing.password.get_secret_value()
    else:
        password = payload.password.get_secret_value()
    profile = ConnectionProfile(
        base_url=payload.base_url,
        username=payload.username,
        password=password,
        verify_tls=payload.verify_tls,
        timeout_seconds=payload.timeout_seconds,
        source="database",
    )
    await runtime.database.save_profile(profile)
    await runtime.discovery.reset_client()
    await runtime.discovery.start_refresh("configuration_saved")
    runtime.scheduler.reschedule()
    return await config_status(runtime)


@router.get("/topology", response_model=TopologySnapshot)
async def topology(runtime: RuntimeDependency) -> TopologySnapshot:
    return await runtime.discovery.get_topology()


@router.post("/topology/refresh", status_code=202)
async def refresh_topology(
    request: Request,
    runtime: RuntimeDependency,
) -> JSONResponse:
    await runtime.rate_limiter.check(
        _client_key(request, "manual-refresh"),
        limit=30,
        window_seconds=60,
    )
    if not await runtime.discovery.client_manager.configured():
        raise NotConfiguredError()
    ticket = await runtime.discovery.start_refresh("manual")
    return JSONResponse(
        status_code=202,
        content={
            "accepted": True,
            "in_progress": True,
            "correlation_id": ticket.correlation_id,
            "reused": ticket.reused,
        },
    )


@router.get("/settings", response_model=DisplaySettings)
async def get_settings(runtime: RuntimeDependency) -> DisplaySettings:
    return await runtime.database.load_settings()


@router.put("/settings", response_model=DisplaySettings)
async def update_settings(
    payload: SettingsUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> DisplaySettings:
    await runtime.rate_limiter.check(
        _client_key(request, "settings-update"),
        limit=60,
        window_seconds=60,
    )
    settings = await runtime.database.update_settings(payload)
    if "refresh_interval_seconds" in payload.model_fields_set:
        runtime.scheduler.reschedule()
    if "network_interfaces" in payload.model_fields_set:
        await runtime.events.publish(
            {
                "type": "topology.updated",
                "reason": "network_settings_updated",
            }
        )
        if await runtime.discovery.client_manager.configured():
            await runtime.discovery.start_refresh(
                "network_settings_updated",
                queue_if_running=True,
            )
    return settings


@router.put("/edges/{edge_id}/style", response_model=EdgeVisualStyle)
async def update_edge_style(
    edge_id: EdgeId,
    payload: EdgeVisualStyleUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> EdgeVisualStyle:
    await runtime.rate_limiter.check(
        _client_key(request, "edge-style-update"),
        limit=120,
        window_seconds=60,
    )
    current = await runtime.discovery.get_topology()
    if edge_id not in {edge.id for edge in current.edges}:
        raise ResourceNotFoundError()
    style = await runtime.database.save_edge_style(edge_id, payload)
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "edge_style_updated",
            "edge_id": edge_id,
        }
    )
    return style


@router.delete("/edges/{edge_id}/style")
async def reset_edge_style(
    edge_id: EdgeId,
    request: Request,
    runtime: RuntimeDependency,
) -> dict[str, bool]:
    await runtime.rate_limiter.check(
        _client_key(request, "edge-style-reset"),
        limit=120,
        window_seconds=60,
    )
    current = await runtime.discovery.get_topology()
    if edge_id not in {edge.id for edge in current.edges}:
        raise ResourceNotFoundError()
    await runtime.database.delete_edge_style(edge_id)
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "edge_style_reset",
            "edge_id": edge_id,
        }
    )
    return {"ok": True}


@router.put(
    "/connections/{connection_id}/interface-override",
    response_model=ConnectionInterfaceOverride,
)
async def update_interface_override(
    connection_id: ConnectionId,
    payload: InterfaceOverrideUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> ConnectionInterfaceOverride:
    await runtime.rate_limiter.check(
        _client_key(request, "interface-override-update"),
        limit=120,
        window_seconds=60,
    )
    current = await runtime.discovery.get_topology()
    if connection_id not in {node.id for node in current.nodes}:
        raise ResourceNotFoundError()
    override = await runtime.database.save_interface_override(
        connection_id,
        payload.interface_name,
    )
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "interface_override_updated",
            "connection_id": connection_id,
        }
    )
    return override


@router.delete("/connections/{connection_id}/interface-override")
async def reset_interface_override(
    connection_id: ConnectionId,
    request: Request,
    runtime: RuntimeDependency,
) -> dict[str, bool]:
    await runtime.rate_limiter.check(
        _client_key(request, "interface-override-reset"),
        limit=120,
        window_seconds=60,
    )
    current = await runtime.discovery.get_topology()
    if connection_id not in {node.id for node in current.nodes}:
        raise ResourceNotFoundError()
    await runtime.database.delete_interface_override(connection_id)
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "interface_override_reset",
            "connection_id": connection_id,
        }
    )
    return {"ok": True}


@router.put(
    "/connections/{connection_id}/visual-routing",
    response_model=DeviceVisualRouting,
)
async def update_device_visual_routing(
    connection_id: ConnectionId,
    payload: DeviceVisualRoutingUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> DeviceVisualRouting:
    """Re-anchor one direct source edge entirely inside ConnectMap."""

    await runtime.rate_limiter.check(
        _client_key(request, "device-visual-routing-update"),
        limit=120,
        window_seconds=60,
    )
    current = await runtime.discovery.get_topology()
    if connection_id not in {node.id for node in current.nodes}:
        raise ResourceNotFoundError()
    logical_edge_id = f"sdex-to-{connection_id}"
    if logical_edge_id not in {edge.id for edge in current.edges}:
        raise TopologyConflictError(
            "Only an existing direct SDEX edge can be re-anchored; visual links are unchanged."
        )
    routing = await runtime.database.save_device_visual_routing(
        connection_id,
        payload.source_handle,
    )
    logger.info(
        "Direct topology edge re-anchored",
        extra={
            "event": "edge_reanchored",
            "connection_id": connection_id,
            "status": payload.source_handle,
        },
    )
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "device_visual_routing_updated",
            "connection_id": connection_id,
            "edge_id": logical_edge_id,
        }
    )
    return routing


@router.delete("/connections/{connection_id}/visual-routing")
async def reset_device_visual_routing(
    connection_id: ConnectionId,
    request: Request,
    runtime: RuntimeDependency,
) -> dict[str, bool]:
    await runtime.rate_limiter.check(
        _client_key(request, "device-visual-routing-reset"),
        limit=120,
        window_seconds=60,
    )
    current = await runtime.discovery.get_topology()
    if connection_id not in {node.id for node in current.nodes}:
        raise ResourceNotFoundError()
    await runtime.database.delete_device_visual_routing(connection_id)
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "device_visual_routing_reset",
            "connection_id": connection_id,
            "edge_id": f"sdex-to-{connection_id}",
        }
    )
    return {"ok": True}


@router.put("/layout")
async def update_layout(
    payload: LayoutUpdate,
    runtime: RuntimeDependency,
) -> dict[str, bool]:
    await runtime.database.save_layout(payload.positions, payload.viewport)
    return {"ok": True}


@router.post("/layout/reset")
async def reset_layout(runtime: RuntimeDependency) -> dict[str, bool]:
    await runtime.discovery.reset_layout()
    return {"ok": True}


@router.get("/visual-topology", response_model=VisualTopologyState)
async def get_visual_topology(runtime: RuntimeDependency) -> VisualTopologyState:
    return (await runtime.discovery.get_topology()).visual_topology


@router.post("/visual-elements", response_model=VisualElement, status_code=201)
async def create_visual_element(
    payload: VisualElementCreate,
    request: Request,
    runtime: RuntimeDependency,
) -> VisualElement:
    await runtime.rate_limiter.check(
        _client_key(request, "visual-element-create"), limit=60, window_seconds=60
    )
    element = await runtime.discovery.visual_topology.create_element(payload)
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "visual_element_created", "id": element.id}
    )
    return element


@router.put("/visual-elements/{element_id}", response_model=VisualElement)
async def update_visual_element(
    element_id: VisualElementId,
    payload: VisualElementUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> VisualElement:
    await runtime.rate_limiter.check(
        _client_key(request, "visual-element-update"), limit=120, window_seconds=60
    )
    current = await runtime.discovery.get_topology()
    element = await runtime.discovery.visual_topology.update_element(element_id, payload, current)
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "visual_element_updated", "id": element.id}
    )
    return element


@router.delete("/visual-elements/{element_id}")
async def delete_visual_element(
    element_id: VisualElementId,
    request: Request,
    runtime: RuntimeDependency,
    eject_members: Annotated[bool, Query()] = False,
    leave_unrouted: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    await runtime.rate_limiter.check(
        _client_key(request, "visual-element-delete"), limit=60, window_seconds=60
    )
    current = await runtime.discovery.get_topology()
    ejected, unrouted = await runtime.discovery.visual_topology.delete_element(
        element_id,
        current,
        eject_members=eject_members,
        leave_unrouted=leave_unrouted,
    )
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "visual_element_deleted", "id": element_id}
    )
    return {
        "ok": True,
        "ejected_member_ids": ejected,
        "unrouted_connection_ids": unrouted,
    }


@router.put("/racks/{rack_id}/members", response_model=RackMembership)
async def put_rack_member(
    rack_id: VisualElementId,
    payload: RackMemberUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> RackMembership:
    await runtime.rate_limiter.check(
        _client_key(request, "rack-member-update"), limit=120, window_seconds=60
    )
    current = await runtime.discovery.get_topology()
    membership = await runtime.discovery.visual_topology.put_member(rack_id, payload, current)
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "rack_membership_updated",
            "rack_id": rack_id,
            "connection_id": payload.connection_id,
        }
    )
    return membership


@router.delete("/racks/{rack_id}/members/{connection_id}")
async def delete_rack_member(
    rack_id: VisualElementId,
    connection_id: ConnectionId,
    request: Request,
    runtime: RuntimeDependency,
) -> dict[str, bool]:
    await runtime.rate_limiter.check(
        _client_key(request, "rack-member-delete"), limit=120, window_seconds=60
    )
    await runtime.discovery.visual_topology.remove_member(rack_id, connection_id)
    await runtime.events.publish(
        {
            "type": "topology.updated",
            "reason": "rack_membership_deleted",
            "rack_id": rack_id,
            "connection_id": connection_id,
        }
    )
    return {"ok": True}


@router.post("/visual-links", response_model=VisualLink, status_code=201)
async def create_visual_link(
    payload: VisualLinkCreate,
    request: Request,
    runtime: RuntimeDependency,
) -> VisualLink:
    await runtime.rate_limiter.check(
        _client_key(request, "visual-link-create"), limit=60, window_seconds=60
    )
    current = await runtime.discovery.get_topology()
    link = await runtime.discovery.visual_topology.create_link(payload, current)
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "visual_link_created", "id": link.id}
    )
    return link


@router.put("/visual-links/{link_id}", response_model=VisualLink)
async def update_visual_link(
    link_id: VisualLinkId,
    payload: VisualLinkUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> VisualLink:
    await runtime.rate_limiter.check(
        _client_key(request, "visual-link-update"), limit=120, window_seconds=60
    )
    current = await runtime.discovery.get_topology()
    link = await runtime.discovery.visual_topology.update_link(link_id, payload, current)
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "visual_link_updated", "id": link.id}
    )
    return link


@router.delete("/visual-links/{link_id}")
async def delete_visual_link(
    link_id: VisualLinkId,
    request: Request,
    runtime: RuntimeDependency,
    leave_unrouted: Annotated[bool, Query()] = False,
) -> dict[str, bool]:
    await runtime.rate_limiter.check(
        _client_key(request, "visual-link-delete"), limit=60, window_seconds=60
    )
    await runtime.discovery.visual_topology.delete_link(link_id, leave_unrouted=leave_unrouted)
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "visual_link_deleted", "id": link_id}
    )
    return {"ok": True}


@router.put("/edges/{edge_id}/route", response_model=EdgeRoute | None)
async def update_edge_route(
    edge_id: EdgeId,
    payload: EdgeRouteUpdate,
    request: Request,
    runtime: RuntimeDependency,
) -> EdgeRoute | None:
    await runtime.rate_limiter.check(
        _client_key(request, "edge-route-update"), limit=120, window_seconds=60
    )
    current = await runtime.discovery.get_topology()
    route = await runtime.discovery.visual_topology.save_route(edge_id, payload, current)
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "edge_route_updated", "edge_id": edge_id}
    )
    return route


@router.delete("/edges/{edge_id}/route")
async def reset_edge_route(
    edge_id: EdgeId,
    request: Request,
    runtime: RuntimeDependency,
) -> dict[str, bool]:
    await runtime.rate_limiter.check(
        _client_key(request, "edge-route-reset"), limit=120, window_seconds=60
    )
    current = await runtime.discovery.get_topology()
    await runtime.discovery.visual_topology.reset_route(edge_id, current)
    await runtime.events.publish(
        {"type": "topology.updated", "reason": "edge_route_reset", "edge_id": edge_id}
    )
    return {"ok": True}


@router.get("/events")
async def events(runtime: RuntimeDependency) -> StreamingResponse:
    async def stream():
        async with runtime.events.subscribe() as queue:
            connected = json.dumps(
                {"type": "connected", "version": __version__},
                separators=(",", ":"),
            )
            yield f"event: topology\ndata: {connected}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    heartbeat = json.dumps(
                        {"type": "heartbeat"},
                        separators=(",", ":"),
                    )
                    yield f"event: topology\ndata: {heartbeat}\n\n"
                else:
                    data = json.dumps(event, separators=(",", ":"), default=str)
                    yield f"event: topology\ndata: {data}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
