from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.adapters import MqttAdapter, SiemensS772Adapter
from app.core.errors import PermissionDeniedError
from app.models.schemas import (
    ConnectionProfile,
    ConnectionStatus,
    EdgeVisualStyleUpdate,
    LayoutPosition,
    ModuleStatus,
)
from app.services.discovery import ClientManager, DiscoveryService, _profile_fingerprint
from app.services.events import EventBroker
from app.services.mock_sdex import BASE_FIXTURES, SYSTEM_FIXTURE
from app.services.sdex_client import NETWORK_INTERFACES_PATH, ModuleUnavailableError


class FakeClient:
    def __init__(
        self,
        *,
        system: Any = None,
        payloads: Mapping[str, Any] | None = None,
        failures: Mapping[str, Exception] | None = None,
        delay: float = 0,
    ) -> None:
        self.system = copy.deepcopy(system if system is not None else SYSTEM_FIXTURE)
        self.payloads = copy.deepcopy(dict(payloads or BASE_FIXTURES))
        self.failures = dict(failures or {})
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.closed = False
        self.system_calls = 0
        self.system_error: Exception | None = None
        self.system_entered = asyncio.Event()
        self.release_system: asyncio.Event | None = None

    async def get_system(self):
        self.system_calls += 1
        self.system_entered.set()
        if self.release_system is not None:
            await self.release_system.wait()
        if self.system_error:
            raise self.system_error
        return copy.deepcopy(self.system)

    async def get_json(self, path: str):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if path in self.failures:
                raise self.failures[path]
            return copy.deepcopy(self.payloads.get(path, []))
        finally:
            self.active -= 1

    async def close(self) -> None:
        self.closed = True


async def make_service(
    tmp_path: Path,
    settings_factory,
    database,
    fake: FakeClient,
    *,
    adapters=None,
    max_concurrency: int = 4,
) -> DiscoveryService:
    await database.save_profile(
        ConnectionProfile(
            base_url="https://sdex.test",
            username="reader",
            password="secret",
            verify_tls=True,
        )
    )
    settings = settings_factory(
        tmp_path,
        max_concurrency=max_concurrency,
    )
    manager = ClientManager(settings, database, client_factory=lambda _profile: fake)
    return DiscoveryService(
        settings,
        database,
        EventBroker(),
        adapters=adapters,
        client_manager=manager,
    )


@pytest.mark.asyncio
async def test_environment_profile_propagates_custom_ca_into_client_identity(
    tmp_path,
    settings_factory,
    database,
) -> None:
    ca_file = tmp_path / "sdex-ca.pem"
    ca_file.write_text("validated when the HTTP client is constructed", encoding="utf-8")
    other_ca_file = tmp_path / "other-ca.pem"
    other_ca_file.write_text("different configured trust source", encoding="utf-8")
    settings = settings_factory(
        tmp_path,
        sdex_base_url="https://sdex.test",
        sdex_username="reader",
        sdex_password="secret",
        sdex_verify_tls=True,
        sdex_ca_cert_path=ca_file,
    )
    manager = ClientManager(settings, database)

    profile = await manager.effective_profile()

    assert profile is not None
    assert profile.source == "environment"
    assert profile.ca_cert_path == ca_file.resolve()
    assert _profile_fingerprint(profile) != _profile_fingerprint(
        profile.model_copy(update={"ca_cert_path": other_ca_file.resolve()})
    )


@pytest.mark.asyncio
async def test_discovery_queries_modules_concurrently_with_limit(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient(delay=0.02)
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        max_concurrency=3,
    )
    snapshot = await service.refresh()
    assert len(snapshot.module_results) == 9
    assert fake.max_active > 1
    assert fake.max_active <= 3
    assert snapshot.partial is False
    assert snapshot.stale is False
    assert snapshot.gateway.status == ConnectionStatus.CONNECTED
    assert snapshot.layout.positions["sdex_gateway:sdex"].model_dump() == {"x": 0.0, "y": 0.0}
    assert snapshot.layout.viewport is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ModuleUnavailableError("missing"), ModuleStatus.UNAVAILABLE),
        (PermissionDeniedError(), ModuleStatus.FORBIDDEN),
        (TimeoutError(), ModuleStatus.TEMPORARY_ERROR),
    ],
)
async def test_module_errors_are_isolated(
    tmp_path,
    settings_factory,
    database,
    failure,
    expected,
) -> None:
    endpoint = MqttAdapter.endpoint
    fake = FakeClient(failures={endpoint: failure})
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[SiemensS772Adapter(), MqttAdapter()],
    )
    snapshot = await service.refresh()
    by_module = {result.module: result for result in snapshot.module_results}
    assert by_module["mqtt"].status == expected
    assert by_module["siemenss72"].status == ModuleStatus.OK
    assert any(node.source_module == "siemenss72" for node in snapshot.nodes)
    assert snapshot.partial is True


@pytest.mark.asyncio
async def test_invalid_module_json_is_parse_error_not_global_failure(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient(payloads={MqttAdapter.endpoint: "invalid-shape"})
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[MqttAdapter()],
    )
    snapshot = await service.refresh()
    assert snapshot.module_results[0].status == ModuleStatus.PARSE_ERROR
    assert snapshot.stale is False
    assert snapshot.partial is True


@pytest.mark.asyncio
async def test_gateway_loss_preserves_snapshot_and_marks_every_node_stale(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient()
    service = await make_service(tmp_path, settings_factory, database, fake)
    fresh = await service.refresh()
    old_statuses = {node.id: node.status for node in fresh.nodes}
    fake.system_error = OSError("network unavailable password=do-not-log")

    stale = await service.refresh()
    assert stale.stale is True
    assert stale.gateway.status == ConnectionStatus.UNKNOWN
    assert stale.last_successful_refresh == fresh.last_successful_refresh
    assert {node.id: node.status for node in stale.nodes} == old_statuses
    assert all(node.stale for node in stale.nodes)
    assert "do-not-log" not in (stale.last_error or "")


@pytest.mark.asyncio
async def test_partial_refresh_keeps_failed_module_previous_nodes_as_stale(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient()
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[SiemensS772Adapter(), MqttAdapter()],
    )
    fresh = await service.refresh()
    assert any(node.source_module == "mqtt" for node in fresh.nodes)
    fake.failures[MqttAdapter.endpoint] = TimeoutError()
    partial = await service.refresh()
    mqtt_nodes = [node for node in partial.nodes if node.source_module == "mqtt"]
    s7_nodes = [node for node in partial.nodes if node.source_module == "siemenss72"]
    assert partial.partial is True
    assert mqtt_nodes and all(node.stale for node in mqtt_nodes)
    assert s7_nodes and not any(node.stale for node in s7_nodes)


@pytest.mark.asyncio
async def test_simultaneous_refresh_requests_share_one_task(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient()
    fake.release_system = asyncio.Event()
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[MqttAdapter()],
    )
    first = await service.start_refresh("manual")
    await fake.system_entered.wait()
    second = await service.start_refresh("manual")
    assert second.task is first.task
    assert second.correlation_id == first.correlation_id
    assert second.reused is True
    fake.release_system.set()
    await first.task


@pytest.mark.asyncio
async def test_network_setting_refresh_is_queued_behind_inflight_discovery(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient()
    fake.release_system = asyncio.Event()
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[],
    )
    first = await service.start_refresh("scheduled")
    await fake.system_entered.wait()
    queued = await service.start_refresh(
        "network_settings_updated",
        queue_if_running=True,
    )
    assert queued.reused is True
    fake.release_system.set()
    await first.task
    for _attempt in range(20):
        if fake.system_calls >= 2 and not service.refresh_in_progress:
            break
        await asyncio.sleep(0.01)
    assert fake.system_calls == 2


@pytest.mark.asyncio
async def test_reset_client_cancels_inflight_refresh_before_profile_handoff(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient()
    fake.release_system = asyncio.Event()
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[MqttAdapter()],
    )
    ticket = await service.start_refresh("old_profile")
    await fake.system_entered.wait()
    await service.reset_client()
    assert ticket.task.cancelled()
    assert service.refresh_in_progress is False
    assert fake.closed is True


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("Running", ConnectionStatus.CONNECTED),
        ("Halted", ConnectionStatus.DEGRADED),
        ("VendorFutureState", ConnectionStatus.UNKNOWN),
    ],
)
@pytest.mark.asyncio
async def test_gateway_system_status_is_not_invented(
    tmp_path,
    settings_factory,
    database,
    raw_status,
    expected,
) -> None:
    system = dict(SYSTEM_FIXTURE, status=raw_status, allConnected=False)
    fake = FakeClient(system=system)
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[],
    )
    snapshot = await service.refresh()
    assert snapshot.gateway.status == expected


@pytest.mark.asyncio
async def test_gateway_metadata_is_allowlisted_and_legacy_icons_are_normalized(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient(system=dict(SYSTEM_FIXTURE, password="must-not-appear"))
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[SiemensS772Adapter()],
    )
    fresh = await service.refresh()
    assert "password" not in fresh.gateway.metadata
    legacy = fresh.model_copy(
        update={
            "gateway": fresh.gateway.model_copy(update={"icon": "/assets/SDEX.svg"}),
            "nodes": [node.model_copy(update={"icon": "/assets/S7_2.svg"}) for node in fresh.nodes],
        }
    )
    await database.save_snapshot(legacy)
    served = await service.get_topology()
    assert served.gateway.icon == "/icons/SDEX.svg"
    assert served.nodes[0].icon == "/icons/S7_2.svg"


@pytest.mark.asyncio
async def test_old_firmware_without_netif_remains_healthy_and_unresolved(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient(failures={NETWORK_INTERFACES_PATH: ModuleUnavailableError("old firmware")})
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[SiemensS772Adapter()],
    )
    snapshot = await service.refresh()
    assert snapshot.partial is False
    assert snapshot.network_interfaces == []
    assert len(snapshot.edges) == 1
    assert snapshot.edges[0].target_handle is None
    assert snapshot.nodes[0].interface_assignment is not None
    assert snapshot.nodes[0].interface_assignment.resolved is False


@pytest.mark.asyncio
async def test_derived_assignments_are_recomputed_and_not_saved_as_user_state(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient()
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[SiemensS772Adapter()],
    )
    returned = await service.refresh()
    assert returned.edges
    assert returned.nodes[0].interface_assignment is not None

    cached = await database.load_snapshot()
    assert cached is not None
    assert cached.edges == []
    assert cached.nodes[0].interface_assignment is None
    recalculated = await service.get_topology()
    assert recalculated.edges
    assert recalculated.nodes[0].interface_assignment is not None


@pytest.mark.asyncio
async def test_edge_style_survives_temporary_connection_disappearance(
    tmp_path,
    settings_factory,
    database,
) -> None:
    fake = FakeClient()
    service = await make_service(
        tmp_path,
        settings_factory,
        database,
        fake,
        adapters=[SiemensS772Adapter()],
    )
    first = await service.refresh()
    edge_id = first.edges[0].id
    await database.save_edge_style(
        edge_id,
        EdgeVisualStyleUpdate(
            sheath_color="#123456",
            flow_color="#ABCDEF",
            reverse_flow=True,
        ),
    )

    original = copy.deepcopy(fake.payloads[SiemensS772Adapter.endpoint])
    fake.payloads[SiemensS772Adapter.endpoint] = []
    disappeared = await service.refresh()
    assert disappeared.edges == []
    assert edge_id in await database.load_edge_styles()

    fake.payloads[SiemensS772Adapter.endpoint] = original
    returned = await service.refresh()
    assert returned.edges[0].style is not None
    assert returned.edges[0].style.sheath_color == "#123456"
    assert returned.edges[0].style.reverse_flow is True


@pytest.mark.asyncio
async def test_preview_reflows_v1_layout_once_but_production_preserves_it(
    tmp_path,
    settings_factory,
    database,
) -> None:
    old = LayoutPosition(node_id="sdex_gateway:sdex", x=123, y=456)
    await database.save_layout([old], None)
    await database.set_layout_visual_version(1)

    production_fake = FakeClient()
    production = await make_service(
        tmp_path,
        settings_factory,
        database,
        production_fake,
        adapters=[],
    )
    production_snapshot = await production.refresh()
    assert production_snapshot.layout.positions["sdex_gateway:sdex"].model_dump() == {
        "x": 123.0,
        "y": 456.0,
    }
    assert production_snapshot.layout.visual_version == 1

    mock_settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    preview = DiscoveryService(mock_settings, database, EventBroker(), adapters=[])
    preview_snapshot = await preview.refresh()
    assert preview_snapshot.layout.positions["sdex_gateway:sdex"].model_dump() == {
        "x": 0.0,
        "y": 0.0,
    }
    assert preview_snapshot.layout.visual_version == 2
    await database.save_layout(
        [LayoutPosition(node_id="sdex_gateway:sdex", x=77, y=88)],
        None,
    )
    second_preview = await preview.refresh()
    assert second_preview.layout.positions["sdex_gateway:sdex"].model_dump() == {
        "x": 77.0,
        "y": 88.0,
    }
