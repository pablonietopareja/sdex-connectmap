"""Verify a synthetic SQLite/key upgrade from an explicit 1.0.0 source checkout."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_PASSWORD = "synthetic-upgrade-password"  # noqa: S105 - synthetic fixture, never a real account


async def worker(source: Path, storage: Path, mode: str) -> dict:
    # Separate interpreters ensure the baseline really imports its own modules.
    # No runtime/scheduler/client is started, so even the dummy profile is never used remotely.
    sys.path.insert(0, str(source / "backend"))
    from app import __version__
    from app.core.security import CredentialCipher
    from app.models.schemas import (
        ConnectionNode,
        ConnectionProfile,
        EdgeRouteUpdate,
        EdgeVisualStyleUpdate,
        LayoutPosition,
        ManualNetworkInterface,
        NetworkInterface,
        Position,
        SettingsUpdate,
        TopologySnapshot,
        Viewport,
        VisualElement,
        VisualLink,
    )
    from app.persistence import Database

    if mode == "seed" and __version__ != "1.0.0":
        raise ValueError("The baseline must be the actual 1.0.0 source")
    cipher = CredentialCipher.from_settings(storage, None)
    database = Database(storage / "connectmap.db", cipher)
    await database.initialize()
    if mode == "seed":
        timestamp = datetime(2026, 10, 14, tzinfo=UTC)
        gateway = ConnectionNode(
            id="sdex_gateway:sdex",
            type="sdex_gateway",
            display_name="Synthetic gateway",
            enabled=True,
            status="connected",
            source_module="core",
            icon="/icons/SDEX.svg",
        )
        nodes = [
            ConnectionNode(
                id=f"modbus:upgrade-meter-{index}",
                type="modbus",
                display_name=f"Synthetic meter {index}",
                address=f"192.0.2.{20 + index}",
                port=502,
                enabled=True,
                licensed=True,
                status="connected",
                source_module="modbus",
                icon="/icons/Modbus.svg",
            )
            for index in range(2)
        ]
        await database.save_profile(
            ConnectionProfile(
                base_url="https://sdex.invalid",
                username="synthetic-reader",
                password=SYNTHETIC_PASSWORD,
                verify_tls=True,
                timeout_seconds=15,
            )
        )
        await database.update_settings(
            SettingsUpdate(
                refresh_interval_seconds=600,
                show_not_enabled=True,
                theme="light",
                network_interfaces=[
                    ManualNetworkInterface(
                        name="eth1", addresses=[{"address": "192.0.2.1", "prefix_length": 24}]
                    )
                ],
            )
        )
        await database.save_snapshot(
            TopologySnapshot(
                gateway=gateway,
                nodes=nodes,
                network_interfaces=[
                    NetworkInterface(
                        name="eth1", addresses=[{"address": "192.0.2.1", "prefix_length": 24}]
                    )
                ],
                generated_at=timestamp,
                last_successful_refresh=timestamp,
            )
        )
        rack = VisualElement(
            id="rack:00000000-0000-4000-8000-000000000001",
            type="rack",
            name="Upgrade rack",
            position=Position(x=100, y=200),
            width=1084,
            height=354,
            rows=1,
            columns=3,
            external_interface="eth1",
            created_at=timestamp,
            updated_at=timestamp,
        )
        switch = VisualElement(
            id="switch:00000000-0000-4000-8000-000000000002",
            type="switch",
            name="Upgrade switch",
            position=Position(x=500, y=200),
            width=310,
            height=228,
            external_interface="eth1",
            created_at=timestamp,
            updated_at=timestamp,
        )
        await database.save_visual_element(rack)
        await database.save_visual_element(switch)
        for column, node in enumerate(nodes):
            await database.save_rack_membership(
                rack.id, node, 0, column, unresolved_interface_confirmed=False
            )
        link = VisualLink(
            id="visual-link:00000000-0000-4000-8000-000000000003",
            source=rack.id,
            target=switch.id,
            source_handle="right",
            target_handle="left",
            external_interface="eth1",
            created_at=timestamp,
            updated_at=timestamp,
        )
        await database.save_visual_link(link)
        direct_edge = f"sdex-to-{nodes[0].id}"
        for edge_id in (link.id, direct_edge):
            await database.save_edge_route(
                edge_id,
                EdgeRouteUpdate(
                    routing_mode="orthogonal",
                    waypoints=[{"id": "upgrade-bend", "x": 250, "y": 330, "kind": "corner"}],
                ),
            )
            await database.save_edge_style(
                edge_id,
                EdgeVisualStyleUpdate(
                    sheath_color="#123456", flow_color="#654321", reverse_flow=True
                ),
            )
        await database.save_device_visual_routing(nodes[1].id, "bottom")
        await database.save_interface_override(nodes[0].id, "eth1")
        await database.save_layout(
            [
                LayoutPosition(node_id=nodes[0].id, x=44, y=-55),
                LayoutPosition(node_id=rack.id, x=100, y=200),
            ],
            Viewport(x=12, y=-24, zoom=1.25),
        )

    profile = await database.load_profile()
    assert profile is not None
    assert profile.password.get_secret_value() == SYNTHETIC_PASSWORD
    snapshot = await database.load_snapshot()
    assert snapshot is not None
    assert [node.id for node in snapshot.nodes] == [
        "modbus:upgrade-meter-0",
        "modbus:upgrade-meter-1",
    ]
    visual = await database.load_visual_topology()
    assert len(visual.elements) == 2 and len(visual.rack_memberships) == 2
    assert len(visual.links) == 1 and len(visual.routes) == 2
    assert len(await database.load_edge_styles()) == 2
    layout = await database.load_layout()
    assert layout.viewport == Viewport(x=12, y=-24, zoom=1.25)
    if mode == "save":
        await database.update_settings(SettingsUpdate(theme="dark"))
        await database.save_layout(
            [LayoutPosition(node_id="modbus:upgrade-meter-0", x=501, y=-67)], layout.viewport
        )
        await database.save_snapshot(snapshot)

    # Compare all persisted rows, not just a handful of fields that could hide a lost relation.
    tables = {}
    with closing(sqlite3.connect(database.path)) as connection:
        connection.row_factory = sqlite3.Row
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        for name in names:
            quoted_name = '"' + name.replace('"', '""') + '"'
            # Names come from sqlite_master and are quoted as identifiers, never SQL fragments.
            query = f"SELECT * FROM {quoted_name}"  # noqa: S608 - quoted catalog table name
            rows = [dict(row) for row in connection.execute(query)]
            if name == "connection_profile":
                for row in rows:
                    row["encrypted_password"] = hashlib.sha256(
                        row["encrypted_password"].encode()
                    ).hexdigest()
            tables[name] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
    for path in storage.glob("connectmap.db*"):
        assert SYNTHETIC_PASSWORD.encode() not in path.read_bytes()
    return {
        "version": __version__,
        "state": {
            "schema_version": await database.schema_version(),
            "key_sha256": hashlib.sha256((storage / ".connectmap-key").read_bytes()).hexdigest(),
            "profile": profile.model_dump(mode="json", exclude={"password"}),
            "tables": tables,
        },
    }


def run_worker(source: Path, storage: Path, mode: str) -> dict:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("SDEX_", "CONNECTMAP_")) and key != "PYTHONPATH"
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Only explicit source checkouts and generated test state are passed to this worker.
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            str(source),
            str(storage),
            mode,
        ],
        cwd=source,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, help="A clean source checkout of version 1.0.0")
    parser.add_argument("--worker", nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        source, storage, mode = args.worker
        if mode not in {"seed", "read", "save"}:
            parser.error("Invalid internal worker mode")
        print(json.dumps(asyncio.run(worker(Path(source), Path(storage), mode))))
        return
    if args.baseline is None:
        parser.error("--baseline is required; current-source data is not an upgrade baseline")
    baseline = args.baseline.resolve()
    if not (baseline / "backend/app/__init__.py").is_file():
        parser.error("--baseline must contain backend/app from a 1.0.0 source checkout")
    current_version = (ROOT / "VERSION").read_text().strip()
    if current_version == "1.0.0":
        parser.error("The current source must differ from the 1.0.0 baseline")
    with TemporaryDirectory(prefix="connectmap-upgrade-acceptance-") as directory:
        storage = Path(directory)
        original = run_worker(baseline, storage, "seed")
        upgraded = run_worker(ROOT, storage, "read")
        assert original["version"] == "1.0.0" and upgraded["version"] == current_version
        assert original["state"] == upgraded["state"], "The upgrade changed persisted state"
        saved = run_worker(ROOT, storage, "save")
        restarted = run_worker(ROOT, storage, "read")
        assert saved["state"] == restarted["state"], "The new source lost state after restart"
        assert saved["state"]["key_sha256"] == original["state"]["key_sha256"]
        assert saved["state"]["schema_version"] == original["state"]["schema_version"]
        for name, rows in original["state"]["tables"].items():
            if name not in {"display_settings", "node_layout", "viewport", "topology_snapshot"}:
                assert saved["state"]["tables"][name] == rows, f"Upgrade changed {name}"
        settings = saved["state"]["tables"]["display_settings"][0]
        assert settings["theme"] == "dark" and settings["refresh_interval_seconds"] == 600
    print(
        f"PASS: 1.0.0 -> {current_version} synthetic SQLite upgrade; decrypted profile, key, "
        "schema, source identities, viewport, racks, memberships, routes and styles retained; "
        "new-source saves survive a separate-process restart."
    )


if __name__ == "__main__":
    main()
