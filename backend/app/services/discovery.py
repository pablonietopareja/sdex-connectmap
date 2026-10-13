from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.adapters import BaseAdapter, default_adapters
from app.adapters.base import get_field, normalized_key
from app.core.config import AppSettings
from app.core.errors import (
    AuthenticationError,
    DefaultPasswordError,
    NotConfiguredError,
    PermissionDeniedError,
    SDEXParseError,
    SDEXUnavailableError,
)
from app.core.logging import correlation_id_var
from app.core.security import sanitize_text
from app.models.schemas import (
    ConnectionNode,
    ConnectionProfile,
    ConnectionStatus,
    ConnectionType,
    LayoutPosition,
    ModuleResult,
    ModuleStatus,
    NetworkInterface,
    NetworkInterfaceSource,
    SystemInfo,
    TopologySnapshot,
    TopologySummary,
    VisualTopologyState,
)
from app.persistence import Database

from .alarms import build_active_alarms
from .events import EventBroker
from .mock_sdex import MockSDEXClient
from .networking import (
    build_topology_edges,
    merge_network_interfaces,
    parse_network_interfaces,
)
from .sdex_client import (
    NETWORK_INTERFACES_PATH,
    ModuleUnavailableError,
    SDEXClient,
    TransientModuleError,
)
from .visual_topology import VisualTopologyService

logger = logging.getLogger(__name__)
MIN_LAYOUT_NODE_DISTANCE = 400.0
CURRENT_LAYOUT_VISUAL_VERSION = 2
LAYOUT_RING_RADIUS = 550.0
LAYOUT_RING_SPACING = 420.0
LAYOUT_MIN_RING_CAPACITY = 8
LAYOUT_SLOT_ARC = 400.0
LAYOUT_CARD_SLOT_WIDTH = 388.0
LAYOUT_CARD_SLOT_HEIGHT = 264.0


class DiscoveryClient(Protocol):
    async def get_system(self) -> Any: ...

    async def get_json(self, path: str) -> Any: ...

    async def close(self) -> None: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_system(payload: Any) -> SystemInfo:
    if not isinstance(payload, Mapping):
        raise SDEXParseError("SDEX system response is not a JSON object.")
    return SystemInfo(
        product_type=_optional_string(get_field(payload, "productType", "product", "ProductType")),
        api_version=_optional_string(
            get_field(payload, "httpAPI", "apiVersion", "version", "Version")
        ),
        status=_optional_string(get_field(payload, "status", "Status")),
        fqdn=_optional_string(get_field(payload, "fqdn", "FQDN")),
        hostname=_optional_string(get_field(payload, "hostname", "hostName", "Hostname")),
        http_api=get_field(payload, "httpAPI", "HttpAPI"),
        os=_optional_string(get_field(payload, "OS", "os", "operatingSystem")),
        arch=_optional_string(get_field(payload, "arch", "architecture")),
        demo=_optional_bool(get_field(payload, "demo", "Demo")),
        all_connected=_optional_bool(get_field(payload, "allConnected", "AllConnected")),
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        if value.strip().casefold() in {"true", "yes", "1"}:
            return True
        if value.strip().casefold() in {"false", "no", "0"}:
            return False
    return None


def build_summary(nodes: list[ConnectionNode]) -> TopologySummary:
    by_type: dict[str, int] = {item.value: 0 for item in ConnectionType}
    by_type.pop(ConnectionType.SDEX_GATEWAY.value, None)
    for node in nodes:
        by_type[str(node.type)] = by_type.get(str(node.type), 0) + 1
    return TopologySummary(
        total_configured=len(nodes),
        enabled=sum(1 for node in nodes if node.enabled),
        connected=sum(1 for node in nodes if node.status == ConnectionStatus.CONNECTED),
        disconnected=sum(1 for node in nodes if node.status == ConnectionStatus.DISCONNECTED),
        disabled=sum(1 for node in nodes if node.status == ConnectionStatus.DISABLED),
        unknown_degraded=sum(
            1
            for node in nodes
            if node.status
            in {
                ConnectionStatus.UNKNOWN,
                ConnectionStatus.DEGRADED,
                ConnectionStatus.UNLICENSED,
            }
        ),
        by_type=by_type,
    )


def _profile_fingerprint(profile: ConnectionProfile) -> str:
    password_digest = hashlib.sha256(
        profile.password.get_secret_value().encode("utf-8")
    ).hexdigest()
    ca_cert_path = str(profile.ca_cert_path) if profile.ca_cert_path is not None else ""
    raw = (
        f"{profile.base_url}\0{profile.username}\0{password_digest}\0"
        f"{profile.verify_tls}\0{ca_cert_path}\0{profile.timeout_seconds}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ClientManager:
    def __init__(
        self,
        settings: AppSettings,
        database: Database,
        client_factory: Callable[[ConnectionProfile], DiscoveryClient] = SDEXClient,
    ) -> None:
        self.settings = settings
        self.database = database
        self.client_factory = client_factory
        self._client: DiscoveryClient | None = None
        self._fingerprint: str | None = None
        self._lock = asyncio.Lock()

    async def effective_profile(self) -> ConnectionProfile | None:
        database_profile = await self.database.load_profile()
        if database_profile is not None:
            return database_profile
        if self.settings.environment_profile_complete:
            return ConnectionProfile(
                base_url=self.settings.sdex_base_url,
                username=self.settings.sdex_username,
                password=self.settings.sdex_password,
                verify_tls=self.settings.sdex_verify_tls,
                timeout_seconds=self.settings.request_timeout_seconds,
                source="environment",
                ca_cert_path=self.settings.sdex_ca_cert_path,
            )
        return None

    async def configured(self) -> bool:
        return self.settings.mock_mode or await self.effective_profile() is not None

    async def get(self) -> DiscoveryClient:
        async with self._lock:
            if self.settings.mock_mode:
                if self._client is None or not isinstance(self._client, MockSDEXClient):
                    if self._client is not None:
                        await self._client.close()
                    self._client = MockSDEXClient(self.settings.mock_scenario)
                    self._fingerprint = "mock"
                return self._client

            profile = await self.effective_profile()
            if profile is None:
                raise NotConfiguredError()
            fingerprint = _profile_fingerprint(profile)
            if self._client is None or self._fingerprint != fingerprint:
                if self._client is not None:
                    await self._client.close()
                self._client = self.client_factory(profile)
                self._fingerprint = fingerprint
            return self._client

    async def invalidate(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.close()
            self._client = None
            self._fingerprint = None

    async def close(self) -> None:
        await self.invalidate()


@dataclass(frozen=True, slots=True)
class RefreshTicket:
    correlation_id: str
    task: asyncio.Task[TopologySnapshot]
    reused: bool


@dataclass(slots=True)
class _AdapterOutcome:
    adapter: BaseAdapter
    nodes: list[ConnectionNode]
    result: ModuleResult


class DiscoveryService:
    def __init__(
        self,
        settings: AppSettings,
        database: Database,
        events: EventBroker,
        *,
        adapters: list[BaseAdapter] | None = None,
        client_manager: ClientManager | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.events = events
        self.adapters = default_adapters() if adapters is None else adapters
        self.client_manager = client_manager or ClientManager(settings, database)
        self.visual_topology = VisualTopologyService(database)
        self._reset_lock = asyncio.Lock()
        self._task_lock = asyncio.Lock()
        self._active_task: asyncio.Task[TopologySnapshot] | None = None
        self._active_correlation_id: str | None = None
        self._queued_trigger: str | None = None

    @property
    def refresh_in_progress(self) -> bool:
        return self._active_task is not None and not self._active_task.done()

    async def start_refresh(
        self,
        trigger: str = "manual",
        *,
        queue_if_running: bool = False,
    ) -> RefreshTicket:
        async with self._reset_lock:
            async with self._task_lock:
                if self._active_task is not None and not self._active_task.done():
                    if queue_if_running:
                        self._queued_trigger = trigger
                    return RefreshTicket(
                        correlation_id=self._active_correlation_id or "unknown",
                        task=self._active_task,
                        reused=True,
                    )
                correlation_id = uuid.uuid4().hex
                task = asyncio.create_task(
                    self._execute_refresh(correlation_id, trigger),
                    name=f"connectmap-refresh-{correlation_id[:8]}",
                )
                self._active_task = task
                self._active_correlation_id = correlation_id
                return RefreshTicket(
                    correlation_id=correlation_id,
                    task=task,
                    reused=False,
                )

    async def refresh(self, trigger: str = "manual") -> TopologySnapshot:
        ticket = await self.start_refresh(trigger)
        return await asyncio.shield(ticket.task)

    async def _execute_refresh(
        self,
        correlation_id: str,
        trigger: str,
    ) -> TopologySnapshot:
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        logger.info(
            "Topology refresh started",
            extra={"event": "refresh_started", "status": trigger},
        )
        await self.events.publish(
            {
                "type": "refresh.started",
                "correlation_id": correlation_id,
                "trigger": trigger,
            }
        )
        try:
            snapshot = await self._discover()
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "Topology refresh completed",
                extra={
                    "event": "refresh_completed",
                    "duration_ms": elapsed,
                    "status": "partial" if snapshot.partial else "ok",
                    "count": len(snapshot.nodes),
                },
            )
            await self.events.publish(
                {
                    "type": "topology.updated",
                    "correlation_id": correlation_id,
                    "generated_at": (
                        snapshot.generated_at.isoformat() if snapshot.generated_at else None
                    ),
                    "partial": snapshot.partial,
                    "stale": snapshot.stale,
                }
            )
            return snapshot
        except asyncio.CancelledError:
            logger.info("Topology refresh cancelled", extra={"event": "refresh_cancelled"})
            raise
        finally:
            correlation_id_var.reset(token)
            queued_trigger: str | None = None
            async with self._task_lock:
                if self._active_task is asyncio.current_task():
                    self._active_task = None
                    self._active_correlation_id = None
                    queued_trigger = self._queued_trigger
                    self._queued_trigger = None
            if queued_trigger is not None:
                await self.start_refresh(queued_trigger)

    async def _discover(self) -> TopologySnapshot:
        previous = await self.database.load_snapshot()
        try:
            client = await self.client_manager.get()
            system_payload = await client.get_system()
            system_info = normalize_system(system_payload)
        except Exception as exc:
            snapshot = await self._stale_snapshot(previous, exc)
            await self.database.save_snapshot(self._without_derived_topology(snapshot))
            logger.warning(
                "SDEX gateway communication failed; serving stale snapshot",
                extra={"event": "gateway_unavailable", "status": type(exc).__name__},
            )
            await self.events.publish(
                {
                    "type": "refresh.failed",
                    "message": snapshot.last_error,
                    "stale": True,
                }
            )
            return await self._overlay_topology(snapshot)

        observed_at = utc_now()
        previous_nodes = {node.id: node for node in previous.nodes} if previous else {}
        previous_gateway = previous.gateway if previous else None
        gateway = self._gateway_node(
            system_info,
            observed_at=observed_at,
            previous=previous_gateway,
            client=client,
        )
        semaphore = asyncio.Semaphore(self.settings.max_concurrency)
        outcome_values = await asyncio.gather(
            self._fetch_network_interfaces(client, semaphore),
            *[
                self._fetch_adapter(
                    adapter,
                    client,
                    semaphore,
                    observed_at,
                    previous_nodes,
                )
                for adapter in self.adapters
            ],
        )
        discovered_interfaces = outcome_values[0]
        outcomes = outcome_values[1:]
        manual_interfaces = await self.database.load_manual_network_interfaces()
        network_interfaces = merge_network_interfaces(
            discovered_interfaces,
            manual_interfaces,
        )

        nodes: list[ConnectionNode] = []
        module_results: list[ModuleResult] = []
        for outcome in outcomes:
            module_results.append(outcome.result)
            if outcome.result.status == ModuleStatus.OK:
                nodes.extend(outcome.nodes)
            else:
                # Preserve the last known module data without fabricating a new state.
                nodes.extend(
                    previous_node.model_copy(update={"stale": True})
                    for previous_node in previous_nodes.values()
                    if previous_node.source_module == outcome.adapter.module_name
                )

        nodes.sort(key=lambda node: (str(node.type), node.display_name.casefold(), node.id))
        partial = any(result.status != ModuleStatus.OK for result in module_results)
        snapshot = TopologySnapshot(
            gateway=gateway,
            nodes=nodes,
            network_interfaces=network_interfaces,
            module_results=module_results,
            summary=build_summary(nodes),
            generated_at=observed_at,
            last_successful_refresh=observed_at,
            stale=False,
            partial=partial,
            refresh_in_progress=False,
            last_error=("Some SDEX modules could not be refreshed." if partial else None),
            mock_mode=self.settings.mock_mode,
        )
        snapshot.layout = await self._ensure_layout(snapshot)
        await self.database.prune_layout({gateway.id, *(node.id for node in nodes)})
        await self.database.save_snapshot(snapshot)
        return await self._overlay_topology(snapshot)

    async def _fetch_network_interfaces(
        self,
        client: DiscoveryClient,
        semaphore: asyncio.Semaphore,
    ) -> list[NetworkInterface]:
        try:
            async with semaphore:
                payload = await client.get_json(NETWORK_INTERFACES_PATH)
            source = (
                NetworkInterfaceSource.MOCK
                if self.settings.mock_mode
                else NetworkInterfaceSource.SDEX
            )
            return parse_network_interfaces(payload, source=source)
        except (
            ModuleUnavailableError,
            PermissionDeniedError,
            AuthenticationError,
            DefaultPasswordError,
            TimeoutError,
            TransientModuleError,
            SDEXUnavailableError,
            SDEXParseError,
            ValueError,
            TypeError,
        ) as exc:
            logger.info(
                "SDEX network interface information is unavailable: %s",
                type(exc).__name__,
                extra={"event": "network_interfaces_unavailable"},
            )
            return []
        except Exception as exc:
            logger.warning(
                "Unexpected SDEX network interface response failure: %s",
                sanitize_text(exc),
                extra={"event": "network_interfaces_unavailable"},
            )
            return []

    async def _fetch_adapter(
        self,
        adapter: BaseAdapter,
        client: DiscoveryClient,
        semaphore: asyncio.Semaphore,
        observed_at: datetime,
        previous_nodes: Mapping[str, ConnectionNode],
    ) -> _AdapterOutcome:
        started = time.perf_counter()
        status = ModuleStatus.OK
        error: str | None = None
        nodes: list[ConnectionNode] = []
        try:
            async with semaphore:
                payload = await client.get_json(adapter.endpoint)
            nodes = adapter.parse(
                payload,
                observed_at=observed_at,
                previous_nodes=previous_nodes,
            )
        except ModuleUnavailableError:
            status = ModuleStatus.UNAVAILABLE
            error = "Module or endpoint is not available in this SDEX version."
        except PermissionDeniedError:
            status = ModuleStatus.FORBIDDEN
            error = "The configured SDEX user cannot read this module."
        except DefaultPasswordError:
            status = ModuleStatus.DEFAULT_PASSWORD
            error = DefaultPasswordError.public_message
        except AuthenticationError:
            status = ModuleStatus.AUTHENTICATION_ERROR
            error = AuthenticationError.public_message
        except (TimeoutError, TransientModuleError, SDEXUnavailableError):
            status = ModuleStatus.TEMPORARY_ERROR
            error = "The SDEX module is temporarily unavailable."
        except (SDEXParseError, ValueError, TypeError):
            status = ModuleStatus.PARSE_ERROR
            error = "The SDEX module returned an unsupported response."
        except Exception as exc:
            status = ModuleStatus.TEMPORARY_ERROR
            error = "The SDEX module request failed."
            logger.warning(
                "Unexpected module discovery failure: %s",
                sanitize_text(exc),
                extra={"event": "module_failed", "sdex_module": adapter.module_name},
            )
        duration = round((time.perf_counter() - started) * 1000, 2)
        logger.log(
            logging.INFO if status == ModuleStatus.OK else logging.WARNING,
            "SDEX module query completed",
            extra={
                "event": "module_query",
                "sdex_module": adapter.module_name,
                "duration_ms": duration,
                "status": status.value,
                "count": len(nodes),
            },
        )
        return _AdapterOutcome(
            adapter=adapter,
            nodes=nodes,
            result=ModuleResult(
                module=adapter.module_name,
                status=status,
                count=len(nodes),
                error=error,
                duration_ms=duration,
            ),
        )

    def _gateway_node(
        self,
        info: SystemInfo,
        *,
        observed_at: datetime,
        previous: ConnectionNode | None,
        client: DiscoveryClient,
    ) -> ConnectionNode:
        raw_system_status = normalized_key(info.status or "")
        if raw_system_status in {"running", "ready", "active", "ok", "healthy"}:
            status = ConnectionStatus.CONNECTED
            reason = "SDEX reports a running state and its system API is reachable."
        elif raw_system_status in {
            "halted",
            "stopped",
            "fault",
            "faulted",
            "error",
            "degraded",
        }:
            status = ConnectionStatus.DEGRADED
            reason = (
                f"SDEX system API is reachable but reports {info.status or 'a degraded state'}."
            )
        else:
            status = ConnectionStatus.UNKNOWN
            reason = (
                "SDEX system API is reachable, but its system status is unavailable "
                "or unrecognized."
            )
        endpoint_url = None
        if isinstance(client, SDEXClient):
            endpoint_url = client.profile.base_url
        parsed_host = (
            urlsplit(endpoint_url).hostname if endpoint_url else info.fqdn or info.hostname
        )
        last_change = observed_at
        if previous and previous.status == status:
            last_change = previous.last_status_change_at or observed_at
        return ConnectionNode(
            id="sdex_gateway:sdex",
            type=ConnectionType.SDEX_GATEWAY,
            subtype="SDEX Suite",
            display_name=info.product_type or "SDEX",
            address=info.fqdn or endpoint_url,
            host=info.fqdn or info.hostname or parsed_host,
            port=urlsplit(endpoint_url).port if endpoint_url else None,
            endpoint_url=endpoint_url,
            enabled=True,
            licensed=None,
            status=status,
            status_reason=reason,
            source_module="core",
            icon="/icons/SDEX.svg",
            metadata={
                key: value
                for key, value in {
                    "product_type": info.product_type,
                    "api_version": info.api_version,
                    "status": info.status,
                    "fqdn": info.fqdn,
                    "hostname": info.hostname,
                    "http_api": info.http_api,
                    "os": info.os,
                    "arch": info.arch,
                    "demo": info.demo,
                    "all_connected": info.all_connected,
                }.items()
                if value is not None
            },
            last_seen_at=observed_at,
            last_status_change_at=last_change,
            stale=False,
            capabilities={},
        )

    async def _stale_snapshot(
        self,
        previous: TopologySnapshot | None,
        error: Exception,
    ) -> TopologySnapshot:
        now = utc_now()
        public_error = self._public_discovery_error(error)
        if previous is None:
            gateway = ConnectionNode(
                id="sdex_gateway:sdex",
                type=ConnectionType.SDEX_GATEWAY,
                subtype="SDEX Suite",
                display_name="SDEX",
                enabled=True,
                licensed=None,
                status=ConnectionStatus.UNKNOWN,
                status_reason="ConnectMap cannot currently communicate with SDEX.",
                source_module="core",
                icon="/icons/SDEX.svg",
                last_status_change_at=now,
                stale=True,
            )
            snapshot = TopologySnapshot(
                gateway=gateway,
                generated_at=now,
                stale=True,
                partial=True,
                last_error=public_error,
                mock_mode=self.settings.mock_mode,
            )
        else:
            gateway = previous.gateway.model_copy(
                update={
                    "status": ConnectionStatus.UNKNOWN,
                    "status_reason": "ConnectMap cannot currently communicate with SDEX.",
                    "stale": True,
                }
            )
            nodes = [node.model_copy(update={"stale": True}) for node in previous.nodes]
            snapshot = previous.model_copy(
                update={
                    "gateway": gateway,
                    "nodes": nodes,
                    "generated_at": now,
                    "stale": True,
                    "partial": True,
                    "refresh_in_progress": False,
                    "last_error": public_error,
                }
            )
        snapshot.layout = await self.database.load_layout()
        snapshot.summary = build_summary(snapshot.nodes)
        return snapshot

    @staticmethod
    def _public_discovery_error(error: Exception) -> str:
        if isinstance(error, DefaultPasswordError):
            return DefaultPasswordError.public_message
        if isinstance(error, AuthenticationError):
            return AuthenticationError.public_message
        if isinstance(error, PermissionDeniedError):
            return PermissionDeniedError.public_message
        if isinstance(error, NotConfiguredError):
            return NotConfiguredError.public_message
        return "ConnectMap cannot currently communicate with the SDEX gateway."

    async def _ensure_layout(self, snapshot: TopologySnapshot):
        layout = await self.database.load_layout()
        if self.settings.mock_mode and layout.visual_version < CURRENT_LAYOUT_VISUAL_VERSION:
            await self.database.reset_layout(CURRENT_LAYOUT_VISUAL_VERSION)
            layout = await self.database.load_layout()
        pending: list[LayoutPosition] = []
        if snapshot.gateway.id not in layout.positions:
            pending.append(LayoutPosition(node_id=snapshot.gateway.id, x=0, y=0))

        existing_points = [(position.x, position.y) for position in layout.positions.values()]
        existing_points.extend((position.x, position.y) for position in pending)
        missing = [node for node in snapshot.nodes if node.id not in layout.positions]
        base_angles = {
            ConnectionType.SIEMENS_S7_1200_1500.value: math.pi,
            ConnectionType.SIEMENS_S7_300_400.value: math.pi * 0.82,
            ConnectionType.ROCKWELL_ALLEN_BRADLEY.value: math.pi * 1.18,
            ConnectionType.MODBUS.value: math.pi * 1.5,
            ConnectionType.SINUMERIK_840D.value: math.pi * 0.5,
            ConnectionType.FANUC_CNC.value: math.pi * 0.35,
            ConnectionType.OPCUA_REMOTE_SERVER.value: 0.1,
            ConnectionType.OPCUA_LOCAL_ENDPOINT.value: -0.15,
            ConnectionType.MQTT_BROKER.value: -0.45,
        }
        ordered_missing = sorted(
            missing,
            key=lambda node: (
                base_angles.get(str(node.type), 0) % math.tau,
                str(node.type),
                node.id,
            ),
        )
        for node in ordered_missing:
            preferred_angle = base_angles.get(str(node.type), 0) % math.tau
            selected: tuple[float, float] | None = None
            for ring in range(64):
                radius = LAYOUT_RING_RADIUS + ring * LAYOUT_RING_SPACING
                capacity = max(
                    LAYOUT_MIN_RING_CAPACITY,
                    math.floor(math.tau * radius / LAYOUT_SLOT_ARC),
                )
                slot_angles = [math.tau * slot / capacity for slot in range(capacity)]
                slot_angles.sort(
                    key=lambda angle: (
                        abs((angle - preferred_angle + math.pi) % math.tau - math.pi),
                        angle,
                    )
                )
                for angle in slot_angles:
                    x, y = radius * math.cos(angle), radius * math.sin(angle)
                    if any(
                        abs(x - px) < LAYOUT_CARD_SLOT_WIDTH
                        and abs(y - py) < LAYOUT_CARD_SLOT_HEIGHT
                        for px, py in existing_points
                    ):
                        continue
                    selected = (x, y)
                    break
                if selected is not None:
                    break
            if selected is None:
                # The bounded search supports thousands of nodes in practice.
                # This deterministic fallback is defensive and remains finite.
                radius = LAYOUT_RING_RADIUS + 64 * LAYOUT_RING_SPACING
                selected = (
                    radius * math.cos(preferred_angle),
                    radius * math.sin(preferred_angle),
                )
            x, y = selected
            pending.append(LayoutPosition(node_id=node.id, x=x, y=y))
            existing_points.append((x, y))
        if pending:
            await self.database.save_layout(pending, None)
            layout = await self.database.load_layout()
        return layout

    async def get_topology(self) -> TopologySnapshot:
        snapshot = await self.database.load_snapshot()
        if snapshot is None:
            snapshot = await self._stale_snapshot(None, NotConfiguredError())
            snapshot.stale = False
            snapshot.partial = False
            snapshot.last_error = None
        snapshot.refresh_in_progress = self.refresh_in_progress
        snapshot.layout = await self.database.load_layout()
        return await self._overlay_topology(snapshot)

    async def _overlay_topology(self, snapshot: TopologySnapshot) -> TopologySnapshot:
        styles, overrides, visual_routings = await asyncio.gather(
            self.database.load_edge_styles(),
            self.database.load_interface_overrides(),
            self.database.load_device_visual_routings(),
        )
        gateway = self._normalized_icon_node(snapshot.gateway)
        base_nodes = [self._normalized_icon_node(node) for node in snapshot.nodes]
        nodes, edges = build_topology_edges(
            base_nodes,
            gateway.id,
            snapshot.network_interfaces,
            overrides,
            styles,
            visual_routings,
        )
        base = snapshot.model_copy(update={"gateway": gateway, "nodes": nodes, "edges": edges})
        if self.settings.mock_mode and self.settings.mock_scenario == "editor_preview":
            await self.visual_topology.ensure_editor_preview(base)
        overlaid = await self.visual_topology.overlay(base, gateway, nodes, edges, styles)
        profile = None if self.settings.mock_mode else await self.client_manager.effective_profile()
        alarms = build_active_alarms(
            overlaid,
            tls_verification_disabled=bool(profile is not None and not profile.verify_tls),
        )
        return overlaid.model_copy(update={"alarms": alarms})

    @staticmethod
    def _normalized_icon_node(node: ConnectionNode) -> ConnectionNode:
        if node.icon.startswith("/assets/"):
            return node.model_copy(update={"icon": f"/icons/{node.icon.removeprefix('/assets/')}"})
        return node

    @staticmethod
    def _without_derived_topology(snapshot: TopologySnapshot) -> TopologySnapshot:
        return snapshot.model_copy(
            update={
                "nodes": [
                    node.model_copy(update={"interface_assignment": None})
                    for node in snapshot.nodes
                ],
                "edges": [],
                "visual_topology": VisualTopologyState(),
                "alarms": [],
            }
        )

    async def reset_client(self) -> None:
        async with self._reset_lock:
            async with self._task_lock:
                self._queued_trigger = None
            task = self._active_task
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await self.client_manager.invalidate()

    async def reset_layout(self) -> None:
        await self.database.reset_layout()
        snapshot = await self.database.load_snapshot()
        if snapshot is None:
            return
        snapshot.layout = await self._ensure_layout(snapshot)
        await self.database.save_snapshot(self._without_derived_topology(snapshot))

    async def close(self) -> None:
        async with self._task_lock:
            self._queued_trigger = None
        task = self._active_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.client_manager.close()
