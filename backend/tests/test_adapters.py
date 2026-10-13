from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters import (
    AllenBradleyAdapter,
    FanucAdapter,
    ModbusAdapter,
    MqttAdapter,
    OpcUaClientAdapter,
    OpcUaServerAdapter,
    SiemensS732Adapter,
    SiemensS772Adapter,
    SinumerikAdapter,
)
from app.core.errors import SDEXParseError
from app.models.schemas import ConnectionStatus, ConnectionType

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def test_endpoint_credentials_are_removed_from_topology_and_reloaded_snapshots() -> None:
    nodes = MqttAdapter().parse(
        [
            {
                "connectionName": "Synthetic broker",
                "brokerUrl": (
                    "mqtt://uri-user:uri-password@broker.example:8883/mqtt"
                    "?token=query-secret#fragment-secret"
                ),
                "connectionState": "connected",
                "description": "password=description-secret",
            }
        ],
        observed_at=NOW,
    )
    node = nodes[0]
    assert node.endpoint_url == "mqtt://broker.example:8883/mqtt"
    assert node.address == node.endpoint_url
    assert node.host == "broker.example"
    assert node.port == 8883
    rendered = node.model_dump_json()
    for secret in (
        "uri-user",
        "uri-password",
        "query-secret",
        "fragment-secret",
        "description-secret",
    ):
        assert secret not in rendered
    old_snapshot = node.model_dump()
    old_snapshot["endpoint_url"] = "opc.tcp://legacy-user:legacy-password@server.example:4840"
    restored = type(node).model_validate(old_snapshot)
    assert restored.endpoint_url == "opc.tcp://server.example:4840"


@pytest.mark.parametrize(
    ("adapter", "payload", "expected_type", "expected_status"),
    [
        (
            SiemensS772Adapter(),
            [
                {
                    "Name": "S72",
                    "Address": "10.0.0.1",
                    "Enabled": True,
                    "Licensed": True,
                    "ConnectionStatus": True,
                }
            ],
            ConnectionType.SIEMENS_S7_1200_1500,
            ConnectionStatus.CONNECTED,
        ),
        (
            SiemensS732Adapter(),
            [
                {
                    "Name": "S32",
                    "Address": "10.0.0.2",
                    "enabled": "TRUE",
                    "licensed": "true",
                    "connectionStatus": "DISCONNECTED",
                }
            ],
            ConnectionType.SIEMENS_S7_300_400,
            ConnectionStatus.DISCONNECTED,
        ),
        (
            AllenBradleyAdapter(),
            [{"connectionName": "AB", "Address": "10.0.0.3", "Enabled": True}],
            ConnectionType.ROCKWELL_ALLEN_BRADLEY,
            ConnectionStatus.UNKNOWN,
        ),
        (
            ModbusAdapter(),
            [
                {
                    "Name": "MB",
                    "Address": "10.0.0.4",
                    "Enabled": False,
                    "Licensed": True,
                    "ConnectionStatus": False,
                }
            ],
            ConnectionType.MODBUS,
            ConnectionStatus.DISABLED,
        ),
        (
            SinumerikAdapter(),
            [
                {
                    "Name": "840D",
                    "Address": "10.0.0.5",
                    "Enabled": True,
                    "EnableNCK": True,
                    "EnablePLC": True,
                    "ConnectionStatus": True,
                    "ConnectionStatus-PLC": False,
                }
            ],
            ConnectionType.SINUMERIK_840D,
            ConnectionStatus.DEGRADED,
        ),
        (
            FanucAdapter(),
            [
                {
                    "Name": "CNC",
                    "Address": "10.0.0.6",
                    "Enabled": True,
                    "Licensed": False,
                }
            ],
            ConnectionType.FANUC_CNC,
            ConnectionStatus.UNLICENSED,
        ),
        (
            OpcUaClientAdapter(),
            {
                "connections": [
                    {
                        "name": "UA",
                        "URL": "opc.tcp://server.local:4840",
                        "Enabled": True,
                        "ConnectionStatus": "cOnNeCtEd",
                    }
                ]
            },
            ConnectionType.OPCUA_REMOTE_SERVER,
            ConnectionStatus.CONNECTED,
        ),
        (
            OpcUaServerAdapter(),
            [
                {
                    "name": "Local",
                    "endpoint-url": "opc.tcp://localhost:4840",
                    "enabled": True,
                }
            ],
            ConnectionType.OPCUA_LOCAL_ENDPOINT,
            ConnectionStatus.CONNECTED,
        ),
        (
            MqttAdapter(),
            [
                {
                    "connectionName": "Broker",
                    "hostname": "mqtt.local",
                    "port": 1883,
                    "enabled": True,
                    "connectionState": "CONNECTED",
                }
            ],
            ConnectionType.MQTT_BROKER,
            ConnectionStatus.CONNECTED,
        ),
    ],
)
def test_protocol_parsers(
    adapter,
    payload,
    expected_type: ConnectionType,
    expected_status: ConnectionStatus,
) -> None:
    nodes = adapter.parse(payload, observed_at=NOW)
    assert len(nodes) == 1
    assert nodes[0].type == expected_type
    assert nodes[0].status == expected_status
    assert nodes[0].last_seen_at == NOW


@pytest.mark.parametrize(
    "adapter",
    [
        SiemensS772Adapter(),
        SiemensS732Adapter(),
        AllenBradleyAdapter(),
        ModbusAdapter(),
        SinumerikAdapter(),
        FanucAdapter(),
        OpcUaClientAdapter(),
        OpcUaServerAdapter(),
        MqttAdapter(),
    ],
)
@pytest.mark.parametrize("payload", [[], {}, {"connections": []}, None])
def test_empty_responses_are_supported(adapter, payload) -> None:
    assert adapter.parse(payload, observed_at=NOW) == []


def test_missing_fields_do_not_invent_disconnected() -> None:
    node = SiemensS772Adapter().parse([{"Name": "Sparse"}], observed_at=NOW)[0]
    assert node.enabled is True
    assert node.status == ConnectionStatus.UNKNOWN
    assert node.address is None
    assert node.port is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Connected", ConnectionStatus.CONNECTED),
        ("CONNECTED", ConnectionStatus.CONNECTED),
        ("disConnected", ConnectionStatus.DISCONNECTED),
        ("brand-new-state", ConnectionStatus.UNKNOWN),
    ],
)
def test_opcua_status_is_case_insensitive_without_guessing(raw, expected) -> None:
    node = OpcUaClientAdapter().parse(
        [{"name": "UA", "URL": "opc.tcp://ua:4840", "ConnectionStatus": raw}],
        observed_at=NOW,
    )[0]
    assert node.status == expected


def test_opcua_ipv6_url_uses_real_url_parser() -> None:
    node = OpcUaClientAdapter().parse(
        [{"name": "IPv6", "URL": "opc.tcp://[2001:db8::8]:4841"}],
        observed_at=NOW,
    )[0]
    assert node.host == "2001:db8::8"
    assert node.port == 4841
    assert node.endpoint_url == "opc.tcp://[2001:db8::8]:4841"


def test_local_opcua_access_protection_is_not_remote_disconnect() -> None:
    node = OpcUaServerAdapter().parse(
        [
            {
                "endpointName": "Protected",
                "enabled": True,
                "accessProtection": {"endpointStatus": True},
            }
        ],
        observed_at=NOW,
    )[0]
    assert node.status == ConnectionStatus.DEGRADED
    assert "access protection" in node.status_reason.lower()


def test_sinumerik_only_uses_explicitly_enabled_subchannels() -> None:
    node = SinumerikAdapter().parse(
        [
            {
                "ConnectionName": "NCK only",
                "Enabled": True,
                "EnableNCK": True,
                "EnablePLC": False,
                "ConnectionStatus": True,
                "ConnectionStatus-PLC": False,
            }
        ],
        observed_at=NOW,
    )[0]
    assert node.status == ConnectionStatus.CONNECTED
    assert node.capabilities["subchannels"]["plc"]["status"] == "disconnected"


def test_sinumerik_ignores_status_of_disabled_subchannels() -> None:
    node = SinumerikAdapter().parse(
        [
            {
                "Name": "No channels",
                "Enabled": True,
                "EnableNCK": False,
                "EnablePLC": False,
                "ConnectionStatus": False,
                "ConnectionStatus-PLC": False,
            }
        ],
        observed_at=NOW,
    )[0]
    assert node.status == ConnectionStatus.UNKNOWN


@pytest.mark.parametrize("adapter", [AllenBradleyAdapter(), FanucAdapter()])
def test_rockwell_and_fanuc_ignore_ambiguous_generic_status(adapter) -> None:
    node = adapter.parse(
        [{"ConnectionName": "Device", "Enabled": True, "Status": "Connected"}],
        observed_at=NOW,
    )[0]
    assert node.status == ConnectionStatus.UNKNOWN


def test_mqtt_metadata_never_contains_nested_proxy_password() -> None:
    serialized = (
        MqttAdapter()
        .parse(
            [
                {
                    "connectionName": "Broker",
                    "hostname": "mqtt.local",
                    "connectionState": "connected",
                    "proxySettings": {"password": "must-not-leak"},
                }
            ],
            observed_at=NOW,
        )[0]
        .model_dump_json()
    )
    assert "must-not-leak" not in serialized
    assert "proxySettings" not in serialized


def test_duplicate_names_have_order_independent_ids() -> None:
    one = {
        "ConnectionName": "Duplicate",
        "Address": "10.0.0.1",
        "Port": 102,
    }
    two = {
        "ConnectionName": "Duplicate",
        "Address": "10.0.0.2",
        "Port": 102,
    }
    adapter = SiemensS772Adapter()
    forward = {
        node.endpoint_url or node.address: node.id
        for node in adapter.parse([one, two], observed_at=NOW)
    }
    reverse = {
        node.endpoint_url or node.address: node.id
        for node in adapter.parse([two, one], observed_at=NOW)
    }
    assert forward == reverse
    assert len(set(forward.values())) == 2
    assert any(node_id.count(":") == 1 for node_id in forward.values())
    assert any(node_id.count(":") == 2 for node_id in forward.values())


def test_duplicate_id_survives_peer_disappearance_and_reappearance() -> None:
    first = {"Name": "Duplicate", "Address": "10.0.0.1"}
    second = {"Name": "Duplicate", "Address": "10.0.0.2"}
    adapter = SiemensS772Adapter()
    both = adapter.parse([first, second], observed_at=NOW)
    ids_by_address = {node.address: node.id for node in both}
    remaining = adapter.parse(
        [second],
        observed_at=NOW,
        previous_nodes={node.id: node for node in both},
    )
    assert remaining[0].id == ids_by_address["10.0.0.2"]
    reappeared = adapter.parse(
        [second, first],
        observed_at=NOW,
        previous_nodes={remaining[0].id: remaining[0]},
    )
    assert {node.address: node.id for node in reappeared} == ids_by_address


def test_unique_name_id_survives_ip_change() -> None:
    adapter = SiemensS772Adapter()
    before = adapter.parse(
        [{"Name": "Stable PLC", "Address": "10.0.0.1"}],
        observed_at=NOW,
    )[0]
    after = adapter.parse(
        [{"Name": "Stable PLC", "Address": "10.0.9.99"}],
        observed_at=NOW,
        previous_nodes={before.id: before},
    )[0]
    assert after.id == before.id


def test_status_change_timestamp_is_preserved_until_status_changes() -> None:
    adapter = SiemensS772Adapter()
    old_time = datetime(2026, 1, 1, tzinfo=UTC)
    old = adapter.parse(
        [{"Name": "PLC", "ConnectionStatus": True}],
        observed_at=old_time,
    )[0]
    same = adapter.parse(
        [{"Name": "PLC", "ConnectionStatus": True}],
        observed_at=NOW,
        previous_nodes={old.id: old},
    )[0]
    changed = adapter.parse(
        [{"Name": "PLC", "ConnectionStatus": False}],
        observed_at=NOW,
        previous_nodes={old.id: old},
    )[0]
    assert same.last_status_change_at == old_time
    assert changed.last_status_change_at == NOW


def test_invalid_collection_is_isolated_as_parse_error() -> None:
    with pytest.raises(SDEXParseError):
        SiemensS772Adapter().parse("not-json-object", observed_at=NOW)
