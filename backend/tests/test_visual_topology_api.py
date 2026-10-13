from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.main import create_app


def refreshed(client: TestClient) -> dict:
    response = client.post("/api/topology/refresh")
    assert response.status_code == 202
    for _attempt in range(120):
        payload = client.get("/api/topology").json()
        if payload["edges"]:
            return payload
        client.portal.call(asyncio.sleep, 0.02)
    raise AssertionError("mock topology did not finish refreshing")


def create_rack(client: TestClient, *, columns: int = 2) -> dict:
    response = client.post(
        "/api/visual-elements",
        json={
            "type": "rack",
            "name": "Production Rack",
            "position": {"x": -400, "y": 100},
            "rows": 1,
            "columns": columns,
            "external_interface": "eth1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_switch(client: TestClient, *, name: str = "Line Switch") -> dict:
    response = client.post(
        "/api/visual-elements",
        json={
            "type": "switch",
            "name": name,
            "position": {"x": 500, "y": 100},
            "external_interface": "eth1",
            "status_mode": "aggregate",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_rack_membership_capacity_overlay_and_delete_preserve_connections(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        eth1_nodes = [
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth1"
        ]
        rack = create_rack(client)
        assert rack["capacity"] == 2
        assert rack["width"] == 716.0
        assert rack["height"] == 324.0
        for column, node in enumerate(eth1_nodes[:2]):
            response = client.put(
                f"/api/racks/{rack['id']}/members",
                json={"connection_id": node["id"], "row": 0, "column": column},
            )
            assert response.status_code == 200, response.text

        invalid_rack_handle = client.post(
            "/api/visual-links",
            json={
                "source": rack["id"],
                "target": topology["gateway"]["id"],
                "source_handle": "top",
            },
        )
        assert invalid_rack_handle.status_code == 409
        rack_link = client.post(
            "/api/visual-links",
            json={"source": rack["id"], "target": topology["gateway"]["id"]},
        )
        assert rack_link.status_code == 201, rack_link.text
        assert rack_link.json()["source_handle"] == "rack-right"

        full = client.put(
            f"/api/racks/{rack['id']}/members",
            json={"connection_id": eth1_nodes[2]["id"], "row": 0, "column": 1},
        )
        assert full.status_code == 409
        assert full.json()["error"]["code"] == "topology_conflict"

        overlaid = client.get("/api/topology").json()
        assert overlaid["summary"] == topology["summary"]
        assert not {
            f"sdex-to-{eth1_nodes[0]['id']}",
            f"sdex-to-{eth1_nodes[1]['id']}",
        } & {edge["id"] for edge in overlaid["edges"]}
        visual = overlaid["visual_topology"]
        assert len(visual["rack_memberships"]) == 2
        aggregated_rack = next(item for item in visual["elements"] if item["id"] == rack["id"])
        assert aggregated_rack["aggregate"]["status"] == "connected"
        assert aggregated_rack["aggregate"]["total"] == 2
        aggregate_edges = [edge for edge in overlaid["edges"] if edge["source"] == rack["id"]]
        assert len(aggregate_edges) == 1
        assert aggregate_edges[0]["kind"] == "aggregate"
        assert aggregate_edges[0]["aggregate"]["total"] == 2

        shrink = client.put(f"/api/visual-elements/{rack['id']}", json={"columns": 1})
        assert shrink.status_code == 409
        assert shrink.json()["error"]["details"]["overflow_member_ids"] == [eth1_nodes[1]["id"]]
        ejected = client.put(
            f"/api/visual-elements/{rack['id']}",
            json={"columns": 1, "overflow_policy": "eject"},
        )
        assert ejected.status_code == 200
        assert ejected.json()["capacity"] == 1

        guarded = client.delete(f"/api/visual-elements/{rack['id']}")
        assert guarded.status_code == 409
        deleted = client.delete(f"/api/visual-elements/{rack['id']}?eject_members=true")
        assert deleted.status_code == 200
        assert deleted.json()["ejected_member_ids"] == [eth1_nodes[0]["id"]]
        final = client.get("/api/topology").json()
        assert {node["id"] for node in final["nodes"]} == {node["id"] for node in topology["nodes"]}
        assert f"sdex-to-{eth1_nodes[0]['id']}" in {edge["id"] for edge in final["edges"]}


def test_membership_rejects_duplicate_rack_and_interface_mismatch(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        eth1 = next(
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth1"
        )
        eth2 = next(
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth2"
        )
        first = create_rack(client, columns=3)
        second = create_rack(client, columns=3)
        assert (
            client.put(
                f"/api/racks/{first['id']}/members",
                json={"connection_id": eth1["id"], "row": 0, "column": 0},
            ).status_code
            == 200
        )
        duplicate = client.put(
            f"/api/racks/{second['id']}/members",
            json={"connection_id": eth1["id"], "row": 0, "column": 0},
        )
        mismatch = client.put(
            f"/api/racks/{first['id']}/members",
            json={"connection_id": eth2["id"], "row": 0, "column": 1},
        )
        assert duplicate.status_code == mismatch.status_code == 409


def test_rack_rejects_linked_or_service_nodes_and_allows_same_member_slot_move(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        industrial = next(
            node for node in topology["nodes"] if node["type"] == "rockwell_allen_bradley"
        )
        service = next(node for node in topology["nodes"] if node["type"] == "mqtt_broker")
        rack = create_rack(client, columns=3)
        switch = create_switch(client)
        link = client.post(
            "/api/visual-links",
            json={"source": industrial["id"], "target": switch["id"]},
        )
        assert link.status_code == 201
        linked_member = client.put(
            f"/api/racks/{rack['id']}/members",
            json={"connection_id": industrial["id"], "row": 0, "column": 0},
        )
        assert linked_member.status_code == 409
        assert client.delete(f"/api/visual-links/{link.json()['id']}").status_code == 200
        assert (
            client.put(
                f"/api/racks/{rack['id']}/members",
                json={"connection_id": industrial["id"], "row": 0, "column": 0},
            ).status_code
            == 200
        )
        moved = client.put(
            f"/api/racks/{rack['id']}/members",
            json={"connection_id": industrial["id"], "row": 0, "column": 1},
        )
        assert moved.status_code == 200
        memberships = client.get("/api/visual-topology").json()["rack_memberships"]
        assert [(item["connection_id"], item["column"]) for item in memberships] == [
            (industrial["id"], 1)
        ]

        service_rack = client.post(
            "/api/visual-elements",
            json={
                "type": "rack",
                "position": {"x": 0, "y": 0},
                "rows": 1,
                "columns": 3,
                "external_interface": "eth2",
            },
        ).json()
        rejected_service = client.put(
            f"/api/racks/{service_rack['id']}/members",
            json={"connection_id": service["id"], "row": 0, "column": 0},
        )
        assert rejected_service.status_code == 409


def test_switch_links_cycle_handles_route_and_unrouted_state(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        gateway_id = topology["gateway"]["id"]
        device = next(
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth1"
        )
        switch = create_switch(client)
        device_link = client.post(
            "/api/visual-links",
            json={"source": device["id"], "target": switch["id"]},
        )
        assert device_link.status_code == 201, device_link.text
        assert device_link.json()["target_handle"].startswith("left:")
        switch_link = client.post(
            "/api/visual-links",
            json={"source": switch["id"], "target": gateway_id},
        )
        assert switch_link.status_code == 201, switch_link.text
        assert switch_link.json()["source_handle"].startswith("right:")

        self_loop = client.post(
            "/api/visual-links",
            json={"source": switch["id"], "target": switch["id"]},
        )
        duplicate_uplink = client.post(
            "/api/visual-links",
            json={"source": device["id"], "target": gateway_id},
        )
        assert self_loop.status_code == duplicate_uplink.status_code == 409

        edge_id = switch_link.json()["id"]
        style = client.put(
            f"/api/edges/{edge_id}/style",
            json={
                "sheath_color": "#123456",
                "flow_color": "#ABCDEF",
                "reverse_flow": True,
            },
        )
        assert style.status_code == 200, style.text
        route = client.put(
            f"/api/edges/{edge_id}/route",
            json={
                "routing_mode": "orthogonal",
                "waypoints": [{"id": "corner-1", "x": 42.5, "y": -19.0, "kind": "corner"}],
            },
        )
        assert route.status_code == 200, route.text
        assert route.json()["waypoints"][0]["order"] == 0
        persisted = client.get("/api/topology").json()
        assert f"sdex-to-{device['id']}" not in {edge["id"] for edge in persisted["edges"]}
        persisted_edge = next(edge for edge in persisted["edges"] if edge["id"] == edge_id)
        assert persisted_edge["route"]["routing_mode"] == "orthogonal"
        assert persisted["visual_topology"]["routes"][edge_id]["waypoints"][0]["x"] == 42.5

        invalid = client.put(
            f"/api/edges/{edge_id}/route",
            json={
                "routing_mode": "manual",
                "waypoints": [{"id": "bad", "x": "NaN", "y": 0, "kind": "free"}],
            },
        )
        assert invalid.status_code == 422
        assert client.delete(f"/api/edges/{edge_id}/route").status_code == 200
        route_reset = client.get("/api/topology").json()
        assert edge_id not in route_reset["visual_topology"]["routes"]
        assert (
            next(edge for edge in route_reset["edges"] if edge["id"] == edge_id)["style"][
                "reverse_flow"
            ]
            is True
        )

        removed = client.delete(f"/api/visual-links/{device_link.json()['id']}?leave_unrouted=true")
        assert removed.status_code == 200
        after = client.get("/api/topology").json()
        assert device["id"] in after["visual_topology"]["unrouted_connection_ids"]
        assert f"sdex-to-{device['id']}" not in {edge["id"] for edge in after["edges"]}


def test_switch_cycle_is_rejected_and_default_delete_reconnects_real_devices(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        device = next(
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth1"
        )
        first = create_switch(client, name="First")
        second = create_switch(client, name="Second")
        assert (
            client.post(
                "/api/visual-links", json={"source": first["id"], "target": second["id"]}
            ).status_code
            == 201
        )
        cycle = client.post(
            "/api/visual-links", json={"source": second["id"], "target": first["id"]}
        )
        assert cycle.status_code == 409
        device_link = client.post(
            "/api/visual-links", json={"source": device["id"], "target": first["id"]}
        )
        assert device_link.status_code == 201
        device_edge_id = device_link.json()["id"]
        assert (
            client.put(
                f"/api/edges/{device_edge_id}/style",
                json={"sheath_color": "#112233", "flow_color": "#AABBCC"},
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/edges/{device_edge_id}/route",
                json={
                    "routing_mode": "manual",
                    "waypoints": [{"id": "preserved", "x": 15, "y": 25}],
                },
            ).status_code
            == 200
        )
        assert f"sdex-to-{device['id']}" not in {
            edge["id"] for edge in client.get("/api/topology").json()["edges"]
        }
        removed = client.delete(f"/api/visual-elements/{first['id']}")
        assert removed.status_code == 200
        assert removed.json()["unrouted_connection_ids"] == []
        after = client.get("/api/topology").json()
        canonical_edge_id = f"sdex-to-{device['id']}"
        edges = {edge["id"]: edge for edge in after["edges"]}
        assert canonical_edge_id in edges
        assert edges[canonical_edge_id]["style"]["sheath_color"] == "#112233"
        assert (
            after["visual_topology"]["routes"][canonical_edge_id]["waypoints"][0]["id"]
            == "preserved"
        )
        assert device["id"] not in after["visual_topology"]["unrouted_connection_ids"]
        assert second["id"] in {element["id"] for element in after["visual_topology"]["elements"]}


def test_switch_delete_can_leave_real_devices_temporarily_unrouted(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        device = next(
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth1"
        )
        switch = create_switch(client)
        linked = client.post(
            "/api/visual-links",
            json={"source": device["id"], "target": switch["id"]},
        )
        assert linked.status_code == 201, linked.text

        removed = client.delete(f"/api/visual-elements/{switch['id']}?leave_unrouted=true")
        assert removed.status_code == 200, removed.text
        assert removed.json()["unrouted_connection_ids"] == [device["id"]]

        after = client.get("/api/topology").json()
        visual = after["visual_topology"]
        assert switch["id"] not in {element["id"] for element in visual["elements"]}
        assert linked.json()["id"] not in {link["id"] for link in visual["links"]}
        assert visual["unrouted_connection_ids"] == [device["id"]]
        assert f"sdex-to-{device['id']}" not in {edge["id"] for edge in after["edges"]}

        replacement = create_switch(client, name="Replacement")
        reconnected = client.post(
            "/api/visual-links",
            json={"source": device["id"], "target": replacement["id"]},
        )
        assert reconnected.status_code == 201, reconnected.text
        restored = client.get("/api/topology").json()
        assert device["id"] not in restored["visual_topology"]["unrouted_connection_ids"]
        assert reconnected.json()["id"] in {edge["id"] for edge in restored["edges"]}


def test_switch_delete_reconnects_rack_and_switch_children_with_presentation(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        gateway_id = topology["gateway"]["id"]
        member = next(
            node
            for node in topology["nodes"]
            if node["type"] == "rockwell_allen_bradley"
            and node["interface_assignment"]["interface_name"] == "eth1"
        )
        rack = create_rack(client)
        assert (
            client.put(
                f"/api/racks/{rack['id']}/members",
                json={"connection_id": member["id"], "row": 0, "column": 0},
            ).status_code
            == 200
        )
        child = create_switch(client, name="Child")
        parent = create_switch(client, name="Parent")
        rack_link = client.post(
            "/api/visual-links", json={"source": rack["id"], "target": parent["id"]}
        ).json()
        child_link = client.post(
            "/api/visual-links", json={"source": child["id"], "target": parent["id"]}
        ).json()
        parent_link = client.post(
            "/api/visual-links", json={"source": parent["id"], "target": gateway_id}
        ).json()
        for link, color in ((rack_link, "#123456"), (child_link, "#654321")):
            assert (
                client.put(
                    f"/api/edges/{link['id']}/style",
                    json={"sheath_color": color, "flow_color": "#ABCDEF"},
                ).status_code
                == 200
            )
            assert (
                client.put(
                    f"/api/edges/{link['id']}/route",
                    json={
                        "routing_mode": "manual",
                        "waypoints": [{"id": "bend", "x": 10, "y": 20}],
                    },
                ).status_code
                == 200
            )

        removed = client.delete(f"/api/visual-elements/{parent['id']}")
        assert removed.status_code == 200, removed.text
        after = client.get("/api/topology").json()
        visual = after["visual_topology"]
        assert parent["id"] not in {element["id"] for element in visual["elements"]}
        assert {rack["id"], child["id"]} <= {element["id"] for element in visual["elements"]}
        assert member["id"] in {
            membership["connection_id"] for membership in visual["rack_memberships"]
        }
        links = {link["id"]: link for link in visual["links"]}
        assert links[rack_link["id"]]["target"] == gateway_id
        assert links[child_link["id"]]["target"] == gateway_id
        assert parent_link["id"] not in links
        assert {rack_link["id"], child_link["id"]} <= set(visual["routes"])
        edges = {edge["id"]: edge for edge in after["edges"]}
        assert edges[rack_link["id"]]["style"]["sheath_color"] == "#123456"
        assert edges[child_link["id"]]["style"]["sheath_color"] == "#654321"


def test_switch_delete_leave_unrouted_keeps_rack_and_switch_children(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        member = next(
            node
            for node in topology["nodes"]
            if node["type"] == "rockwell_allen_bradley"
            and node["interface_assignment"]["interface_name"] == "eth1"
        )
        rack = create_rack(client)
        assert (
            client.put(
                f"/api/racks/{rack['id']}/members",
                json={"connection_id": member["id"], "row": 0, "column": 0},
            ).status_code
            == 200
        )
        child = create_switch(client, name="Child")
        parent = create_switch(client, name="Parent")
        incoming_ids = {
            client.post(
                "/api/visual-links", json={"source": source, "target": parent["id"]}
            ).json()["id"]
            for source in (rack["id"], child["id"])
        }

        removed = client.delete(f"/api/visual-elements/{parent['id']}?leave_unrouted=true")
        assert removed.status_code == 200, removed.text
        after = client.get("/api/topology").json()
        visual = after["visual_topology"]
        assert {rack["id"], child["id"]} <= {element["id"] for element in visual["elements"]}
        assert not incoming_ids & {link["id"] for link in visual["links"]}
        assert not {rack["id"], child["id"]} & {edge["source"] for edge in after["edges"]}
        assert member["id"] in {
            membership["connection_id"] for membership in visual["rack_memberships"]
        }


def test_placeholder_switch_handles_are_normalized_per_link(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    with TestClient(create_app(settings)) as client:
        topology = refreshed(client)
        devices = [
            node
            for node in topology["nodes"]
            if node["interface_assignment"]["interface_name"] == "eth1"
        ][:2]
        switch = create_switch(client)
        links = []
        for device in devices:
            response = client.post(
                "/api/visual-links",
                json={
                    "source": device["id"],
                    "target": switch["id"],
                    "source_handle": "right:new",
                    "target_handle": "left:new",
                },
            )
            assert response.status_code == 201, response.text
            links.append(response.json())
        assert len({link["source_handle"] for link in links}) == 2
        assert len({link["target_handle"] for link in links}) == 2
        for link in links:
            assert link["source_handle"] == f"right:{link['id']}"
            assert link["target_handle"] == f"left:{link['id']}"
        persisted_links = client.get("/api/visual-topology").json()["links"]
        persisted = {link["id"]: link for link in persisted_links}
        for link in links:
            assert persisted[link["id"]]["target_handle"] == f"left:{link['id']}"


def test_editor_preview_seeds_visual_layer_once_and_keeps_user_edit(
    tmp_path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="editor_preview")
    with TestClient(create_app(settings)) as client:
        first = refreshed(client)
        visual = first["visual_topology"]
        assert {element["type"] for element in visual["elements"]} == {"rack", "switch"}
        assert len(visual["rack_memberships"]) == 2
        assert len(visual["links"]) == 3
        assert {route["routing_mode"] for route in visual["routes"].values()} == {
            "manual",
            "orthogonal",
        }
        rack = next(element for element in visual["elements"] if element["type"] == "rack")
        rack_uplink = next(edge for edge in first["edges"] if edge["source"] == rack["id"])
        assert rack_uplink["source_handle"] == "rack-right"
        assert rack_uplink["route"]["routing_mode"] == "manual"
        renamed = client.put(f"/api/visual-elements/{rack['id']}", json={"name": "Operator Rack"})
        assert renamed.status_code == 200
        refreshed(client)
        state = client.get("/api/visual-topology").json()
        assert (
            next(element for element in state["elements"] if element["id"] == rack["id"])["name"]
            == "Operator Rack"
        )
