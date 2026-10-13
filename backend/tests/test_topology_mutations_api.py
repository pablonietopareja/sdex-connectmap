from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _refreshed_client(client: TestClient) -> dict:
    response = client.post("/api/topology/refresh")
    assert response.status_code == 202
    for _attempt in range(100):
        topology = client.get("/api/topology")
        assert topology.status_code == 200
        payload = topology.json()
        if payload["edges"]:
            return payload
        client.portal.call(asyncio.sleep, 0.02)
    raise AssertionError("visual preview topology did not finish refreshing")


def test_edge_style_validates_normalizes_persists_and_resets(
    tmp_path: Path,
    settings_factory,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    with TestClient(create_app(settings)) as client:
        topology = _refreshed_client(client)
        edge_id = topology["edges"][0]["id"]
        untouched_edge_id = topology["edges"][1]["id"]
        saved = client.put(
            f"/api/edges/{edge_id}/style",
            json={"sheath_color": "#aabbcc", "flow_color": "#10203f"},
        )
        assert saved.status_code == 200
        assert saved.json()["sheath_color"] == "#AABBCC"
        assert saved.json()["flow_color"] == "#10203F"
        assert saved.json()["reverse_flow"] is False
        reversed_style = client.put(
            f"/api/edges/{edge_id}/style",
            json={
                "sheath_color": "#aabbcc",
                "flow_color": "#10203f",
                "reverse_flow": True,
            },
        )
        assert reversed_style.status_code == 200
        assert reversed_style.json()["reverse_flow"] is True
        styled = {edge["id"]: edge["style"] for edge in client.get("/api/topology").json()["edges"]}
        assert styled[edge_id]["sheath_color"] == "#AABBCC"
        assert styled[edge_id]["reverse_flow"] is True
        assert styled[untouched_edge_id] is None

    with TestClient(create_app(settings)) as restarted:
        persisted = {
            edge["id"]: edge["style"] for edge in restarted.get("/api/topology").json()["edges"]
        }
        assert persisted[edge_id]["flow_color"] == "#10203F"
        assert persisted[edge_id]["reverse_flow"] is True
        assert persisted[untouched_edge_id] is None
        reset = restarted.delete(f"/api/edges/{edge_id}/style")
        assert reset.status_code == 200
        assert reset.json() == {"ok": True}
        after_reset = {
            edge["id"]: edge["style"] for edge in restarted.get("/api/topology").json()["edges"]
        }
        assert after_reset[edge_id] is None


@pytest.mark.parametrize("reverse_flow", [0, 1, "false", "true", None, [], {}])
def test_edge_style_rejects_non_boolean_reverse_flow(
    tmp_path: Path,
    settings_factory,
    reverse_flow,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    with TestClient(create_app(settings)) as client:
        edge_id = _refreshed_client(client)["edges"][0]["id"]
        response = client.put(
            f"/api/edges/{edge_id}/style",
            json={
                "sheath_color": "#112233",
                "flow_color": "#445566",
                "reverse_flow": reverse_flow,
            },
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "color",
    [
        "red",
        "#12345",
        "#1234567",
        " #123456",
        "#123456 ",
        "var(--cable)",
        "url(javascript:alert(1))",
        "rgb(1,2,3)",
    ],
)
def test_edge_style_rejects_non_strict_hex_and_arbitrary_css(
    tmp_path: Path,
    settings_factory,
    color: str,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    with TestClient(create_app(settings)) as client:
        edge_id = _refreshed_client(client)["edges"][0]["id"]
        response = client.put(
            f"/api/edges/{edge_id}/style",
            json={"sheath_color": color, "flow_color": "#112233"},
        )
        assert response.status_code == 422
        assert "javascript" not in response.text.casefold()


def test_mutations_reject_well_formed_but_nonexistent_topology_ids(
    tmp_path: Path,
    settings_factory,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    with TestClient(create_app(settings)) as client:
        _refreshed_client(client)
        style = client.put(
            "/api/edges/sdex-to-modbus:does-not-exist/style",
            json={"sheath_color": "#112233", "flow_color": "#445566"},
        )
        override = client.put(
            "/api/connections/modbus:does-not-exist/interface-override",
            json={"interface_name": "eth1"},
        )
        delete = client.delete("/api/edges/sdex-to-modbus:does-not-exist/style")
        assert style.status_code == override.status_code == delete.status_code == 404
        assert style.json()["error"] == {
            "code": "resource_not_found",
            "message": "The requested topology resource does not exist.",
        }


def test_interface_override_is_immediate_removable_and_validated(
    tmp_path: Path,
    settings_factory,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    with TestClient(create_app(settings)) as client:
        topology = _refreshed_client(client)
        eth1_node = next(
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth1"
        )
        connection_id = eth1_node["id"]
        saved = client.put(
            f"/api/connections/{connection_id}/interface-override",
            json={"interface_name": "eth2"},
        )
        assert saved.status_code == 200
        assert saved.json()["interface_name"] == "eth2"
        overridden = next(
            node
            for node in client.get("/api/topology").json()["nodes"]
            if node["id"] == connection_id
        )
        assert overridden["interface_assignment"]["source"] == "manual_override"
        assert overridden["interface_assignment"]["interface_name"] == "eth2"

        invalid = client.put(
            f"/api/connections/{connection_id}/interface-override",
            json={"interface_name": "eth0"},
        )
        assert invalid.status_code == 422
        assert (
            client.delete(f"/api/connections/{connection_id}/interface-override").status_code == 200
        )
        derived = next(
            node
            for node in client.get("/api/topology").json()["nodes"]
            if node["id"] == connection_id
        )
        assert derived["interface_assignment"]["source"] == "subnet"
        assert derived["interface_assignment"]["interface_name"] == "eth1"


def test_manual_eth_settings_round_trip_and_accept_ipv4_netmask_and_ipv6_prefix(
    tmp_path: Path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="stable")
    with TestClient(create_app(settings)) as client:
        response = client.put(
            "/api/settings",
            json={
                "network_interfaces": [
                    {
                        "name": "eth1",
                        "addresses": [
                            {
                                "address": "172.16.1.1",
                                "netmask": "255.255.255.0",
                            }
                        ],
                    },
                    {
                        "name": "eth2",
                        "addresses": [
                            {
                                "address": "fd00:20::1",
                                "prefix_length": 64,
                            }
                        ],
                    },
                ]
            },
        )
        assert response.status_code == 200
        configured = response.json()["network_interfaces"]
        assert configured[0]["addresses"][0]["prefix_length"] == 24
        assert configured[1]["addresses"][0]["address"] == "fd00:20::1"
        assert client.get("/api/settings").json()["network_interfaces"] == configured

        cleared = client.put("/api/settings", json={"network_interfaces": []})
        assert cleared.status_code == 200
        assert cleared.json()["network_interfaces"] == []


def test_mutating_routes_are_rate_limited_through_runtime_limiter(
    tmp_path: Path,
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        mock_scenario="visual_preview",
    )
    with TestClient(create_app(settings)) as client:
        topology = _refreshed_client(client)
        edge_id = topology["edges"][0]["id"]
        connection_id = topology["nodes"][0]["id"]
        runtime = client.app.state.runtime
        operations: list[str] = []

        async def record(key: str, **_kwargs) -> None:
            operations.append(key.split(":", 1)[0])

        monkeypatch.setattr(runtime.rate_limiter, "check", record)
        assert (
            client.put(
                f"/api/edges/{edge_id}/style",
                json={"sheath_color": "#112233", "flow_color": "#445566"},
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/connections/{connection_id}/interface-override",
                json={"interface_name": "eth1"},
            ).status_code
            == 200
        )
        assert client.put("/api/settings", json={"network_interfaces": []}).status_code == 200
        assert operations == [
            "edge-style-update",
            "interface-override-update",
            "settings-update",
        ]
