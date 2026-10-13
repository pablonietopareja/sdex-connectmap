from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.errors import ConfigurationError
from app.core.security import CredentialCipher, sanitize_text
from app.models.schemas import (
    ConnectionNode,
    ConnectionProfile,
    ConnectionStatus,
    ConnectionType,
    EdgeVisualStyleUpdate,
    LayoutPosition,
    ManualNetworkAddress,
    ManualNetworkInterface,
    SettingsUpdate,
    TopologySnapshot,
    Viewport,
)
from app.persistence import Database


@pytest.mark.parametrize(
    "unsafe",
    [
        "password=hunter2 clientNonce=abc serverNonce=def Signature=ghi",
        '{"password":"hunter2","clientNonce":"abc","Auth":"User=a;Signature=x"}',
        "https://alice:hunter2@sdex.local/runtime proxySettings.password=hunter2",
        "Auth: User=admin;Signature=super-secret",
        "mqtt://alice:hunter2@broker.example:8883/mqtt",
        "opc.tcp://alice:hunter2@server.example:4840",
    ],
)
def test_sanitizer_removes_secrets(unsafe: str) -> None:
    sanitized = sanitize_text(unsafe, ("hunter2", "abc", "def", "ghi", "super-secret"))
    for secret in ("hunter2", "abc", "def", "ghi", "super-secret"):
        assert secret not in sanitized
    assert "[REDACTED]" in sanitized


def test_generated_key_is_persistent_and_restrictive(tmp_path: Path) -> None:
    first = CredentialCipher.from_settings(tmp_path, None)
    encrypted = first.encrypt("very-secret")
    second = CredentialCipher.from_settings(tmp_path, None)
    assert second.decrypt(encrypted) == "very-secret"
    key_path = tmp_path / ".connectmap-key"
    assert key_path.exists()
    if os.name != "nt":
        assert key_path.stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
async def test_profile_is_encrypted_and_round_trips(tmp_path: Path) -> None:
    database_path = tmp_path / "connectmap.db"
    db = Database(database_path, CredentialCipher(Fernet.generate_key()))
    await db.initialize()
    profile = ConnectionProfile(
        base_url="https://sdex-suite:443/",
        username="reader",
        password="plain-password",
        verify_tls=False,
        timeout_seconds=9,
    )
    await db.save_profile(profile)
    raw = database_path.read_bytes()
    assert b"plain-password" not in raw
    loaded = await db.load_profile()
    assert loaded is not None
    assert loaded.base_url == "https://sdex-suite"
    assert loaded.username == "reader"
    assert loaded.password.get_secret_value() == "plain-password"
    assert loaded.verify_tls is False
    assert loaded.timeout_seconds == 9
    assert "plain-password" not in loaded.model_dump_json()


@pytest.mark.asyncio
async def test_layout_and_viewport_persist_and_reset(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    path = tmp_path / "connectmap.db"
    db = Database(path, CredentialCipher(key))
    await db.initialize()
    assert (await db.load_layout()).viewport is None
    await db.save_layout(
        [LayoutPosition(node_id="modbus:meter", x=12.5, y=-8.0)],
        Viewport(x=100, y=200, zoom=1.2),
    )

    restarted = Database(path, CredentialCipher(key))
    await restarted.initialize()
    layout = await restarted.load_layout()
    assert layout.positions["modbus:meter"].x == 12.5
    assert layout.viewport is not None
    assert layout.viewport.zoom == 1.2

    await restarted.reset_layout()
    reset = await restarted.load_layout()
    assert reset.positions == {}
    assert reset.viewport is None


@pytest.mark.asyncio
async def test_layout_retention_starts_when_node_becomes_inactive(tmp_path: Path) -> None:
    db = Database(tmp_path / "connectmap.db", CredentialCipher(Fernet.generate_key()))
    await db.initialize()
    await db.save_layout(
        [
            LayoutPosition(node_id="active", x=1, y=1),
            LayoutPosition(node_id="inactive", x=2, y=2),
        ],
        None,
    )
    with sqlite3.connect(db.path) as connection:
        connection.execute("UPDATE node_layout SET updated_at='2000-01-01T00:00:00+00:00'")
    assert await db.prune_layout({"active"}, retention_days=180) == 1
    assert set((await db.load_layout()).positions) == {"active"}
    with sqlite3.connect(db.path) as connection:
        connection.execute(
            "UPDATE node_layout SET updated_at='2000-01-01T00:00:00+00:00' WHERE node_id='active'"
        )
    assert await db.prune_layout(set(), retention_days=180) == 1
    assert (await db.load_layout()).positions == {}


@pytest.mark.asyncio
async def test_settings_are_validated_and_persistent(database: Database) -> None:
    updated = await database.update_settings(
        SettingsUpdate(
            refresh_interval_seconds=900,
            show_not_enabled=True,
            theme="dark",
        )
    )
    assert updated.refresh_interval_seconds == 900
    assert updated.show_not_enabled is True
    assert updated.theme == "dark"
    assert (await database.load_settings()) == updated


@pytest.mark.asyncio
async def test_partial_settings_update_uses_one_atomic_database_operation(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run = database._run
    operation_count = 0

    async def counted_run(operation):
        nonlocal operation_count
        operation_count += 1
        return await original_run(operation)

    monkeypatch.setattr(database, "_run", counted_run)
    updated = await database.update_settings(SettingsUpdate(theme="dark"))

    assert operation_count == 1
    assert updated.theme == "dark"


@pytest.mark.asyncio
async def test_schema_version_is_stored(database: Database) -> None:
    assert await database.schema_version() == 5
    with sqlite3.connect(database.path) as connection:
        assert (
            connection.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()[
                0
            ]
            == 5
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("incompatible_version", [0, 6, 99])
async def test_incompatible_schema_is_rejected_without_overwriting(
    tmp_path: Path,
    incompatible_version: int,
) -> None:
    path = tmp_path / "future-connectmap.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_metadata VALUES (1, ?, 'future')",
            (incompatible_version,),
        )
    database = Database(path, CredentialCipher(Fernet.generate_key()))
    with pytest.raises(ConfigurationError, match="Unsupported ConnectMap database schema"):
        await database.initialize()
    with sqlite3.connect(path) as connection:
        stored_version = connection.execute(
            "SELECT version FROM schema_metadata WHERE singleton=1"
        ).fetchone()[0]
    assert stored_version == incompatible_version


@pytest.mark.asyncio
async def test_transitional_v6_database_is_read_compatible_and_not_downgraded(
    tmp_path: Path,
) -> None:
    path = tmp_path / "transitional-v6.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES (1, 6, 'transitional');
            CREATE TABLE primary_visual_route (
                connection_id TEXT PRIMARY KEY,
                target_element_id TEXT NOT NULL,
                source_handle TEXT,
                target_handle TEXT,
                external_interface TEXT,
                unresolved_interface_confirmed INTEGER NOT NULL DEFAULT 0,
                schema_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO primary_visual_route VALUES (
                'modbus:preserved',
                'switch:00000000-0000-4000-8000-000000000001',
                'right',
                'left:preserved',
                'eth1',
                0,
                1,
                '2026-09-04T00:00:00+00:00',
                '2026-09-04T00:00:00+00:00'
            );
            """
        )

    database = Database(path, CredentialCipher(Fernet.generate_key()))
    await database.initialize()

    assert await database.schema_version() == 6
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT target_element_id FROM primary_visual_route WHERE connection_id=?",
                ("modbus:preserved",),
            )
            .fetchone()[0]
            .startswith("switch:")
        )


def _old_snapshot_payload() -> str:
    snapshot = TopologySnapshot(
        gateway=ConnectionNode(
            id="sdex_gateway:sdex",
            type=ConnectionType.SDEX_GATEWAY,
            display_name="SDEX",
            enabled=True,
            status=ConnectionStatus.CONNECTED,
            source_module="core",
            icon="/icons/SDEX.svg",
        )
    ).model_dump(
        mode="json",
        exclude={"edges", "network_interfaces"},
    )
    snapshot["layout"].pop("visual_version", None)
    import json

    return json.dumps(snapshot)


@pytest.mark.asyncio
async def test_schema_v1_migrates_transactionally_without_losing_snapshot_settings_or_layout(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES (1, 1, 'legacy');
            CREATE TABLE display_settings (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                refresh_interval_seconds INTEGER NOT NULL,
                show_not_enabled INTEGER NOT NULL DEFAULT 0,
                theme TEXT NOT NULL DEFAULT 'system',
                updated_at TEXT NOT NULL
            );
            INSERT INTO display_settings VALUES (1, 900, 1, 'dark', 'legacy');
            CREATE TABLE node_layout (
                node_id TEXT PRIMARY KEY,
                x REAL NOT NULL,
                y REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO node_layout VALUES ('modbus:meter', 12.5, -8.0, 'legacy');
            CREATE TABLE viewport (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                x REAL NOT NULL,
                y REAL NOT NULL,
                zoom REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO viewport VALUES (1, 3.0, 4.0, 1.2, 'legacy');
            CREATE TABLE topology_snapshot (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                payload TEXT NOT NULL,
                last_success_at TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO topology_snapshot VALUES (1, ?, NULL, 'legacy')",
            (_old_snapshot_payload(),),
        )

    database = Database(path, CredentialCipher(Fernet.generate_key()))
    await database.initialize()

    assert await database.schema_version() == 5
    settings = await database.load_settings()
    assert (settings.refresh_interval_seconds, settings.show_not_enabled, settings.theme) == (
        900,
        True,
        "dark",
    )
    layout = await database.load_layout()
    assert layout.positions["modbus:meter"].x == 12.5
    assert layout.viewport is not None and layout.viewport.zoom == 1.2
    assert layout.visual_version == 1
    snapshot = await database.load_snapshot()
    assert snapshot is not None
    assert snapshot.edges == []
    assert snapshot.network_interfaces == []
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "edge_visual_style",
        "connection_interface_override",
        "manual_network_interface",
        "layout_metadata",
    } <= tables


@pytest.mark.asyncio
async def test_schema_v2_style_migrates_with_reverse_flow_default_false(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-v2.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES (1, 2, 'legacy');
            CREATE TABLE edge_visual_style (
                edge_id TEXT PRIMARY KEY,
                sheath_color TEXT NOT NULL,
                flow_color TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            INSERT INTO edge_visual_style VALUES (
                'sdex-to-modbus:legacy',
                '#112233',
                '#445566',
                1,
                '2026-01-01T00:00:00+00:00'
            );
            """
        )

    database = Database(path, CredentialCipher(Fernet.generate_key()))
    await database.initialize()

    assert await database.schema_version() == 5
    loaded = (await database.load_edge_styles())["sdex-to-modbus:legacy"]
    assert loaded.sheath_color == "#112233"
    assert loaded.flow_color == "#445566"
    assert loaded.reverse_flow is False
    assert loaded.schema_version == 1
    with sqlite3.connect(path) as connection:
        column = next(
            row
            for row in connection.execute("PRAGMA table_info(edge_visual_style)")
            if row[1] == "reverse_flow"
        )
        assert column[3] == 1
        assert column[4] == "0"


@pytest.mark.asyncio
async def test_v1_migration_failure_rolls_back_version_and_new_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "rollback.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("INSERT INTO schema_metadata VALUES (1, 1, 'legacy')")

    database = Database(path, CredentialCipher(Fernet.generate_key()))

    def fail_after_create(connection):
        connection.execute("CREATE TABLE migration_probe(value TEXT)")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(database, "_create_version_two_tables", fail_after_create)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        await database.initialize()
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()[
                0
            ]
            == 1
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='migration_probe'"
            ).fetchone()
            is None
        )


@pytest.mark.asyncio
async def test_v2_reverse_flow_migration_failure_rolls_back_schema_and_column(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "rollback-v2.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                singleton INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES (1, 2, 'legacy');
            CREATE TABLE edge_visual_style (
                edge_id TEXT PRIMARY KEY,
                sheath_color TEXT NOT NULL,
                flow_color TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            """
        )

    database = Database(path, CredentialCipher(Fernet.generate_key()))

    def fail_after_alter(connection):
        Database._migrate_version_three(connection)
        raise RuntimeError("injected v3 migration failure")

    monkeypatch.setattr(database, "_migrate_version_three", fail_after_alter)
    with pytest.raises(RuntimeError, match="injected v3 migration failure"):
        await database.initialize()

    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT version FROM schema_metadata WHERE singleton=1").fetchone()[
                0
            ]
            == 2
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(edge_visual_style)")}
        assert "reverse_flow" not in columns


@pytest.mark.asyncio
async def test_styles_overrides_and_manual_networks_persist_independently(
    tmp_path: Path,
) -> None:
    key = Fernet.generate_key()
    path = tmp_path / "persistent-v2.db"
    database = Database(path, CredentialCipher(key))
    await database.initialize()
    style = await database.save_edge_style(
        "sdex-to-modbus:meter",
        EdgeVisualStyleUpdate(
            sheath_color="#aabbcc",
            flow_color="#102030",
            reverse_flow=True,
        ),
    )
    await database.save_interface_override("modbus:meter", "eth2")
    await database.update_settings(
        SettingsUpdate(
            network_interfaces=[
                ManualNetworkInterface(
                    name="eth1",
                    addresses=[
                        ManualNetworkAddress(
                            address="192.168.10.1",
                            prefix_length=24,
                        )
                    ],
                )
            ]
        )
    )

    restarted = Database(path, CredentialCipher(key))
    await restarted.initialize()
    persisted_style = (await restarted.load_edge_styles())[style.edge_id]
    assert persisted_style.sheath_color == "#AABBCC"
    assert persisted_style.reverse_flow is True
    assert persisted_style.schema_version == 2
    assert (await restarted.load_interface_overrides())["modbus:meter"].interface_name == "eth2"
    manual = await restarted.load_manual_network_interfaces()
    assert manual[0].addresses[0].prefix_length == 24

    assert await restarted.delete_edge_style(style.edge_id) is True
    assert await restarted.delete_edge_style(style.edge_id) is False
    assert await restarted.delete_interface_override("modbus:meter") is True
    assert await restarted.delete_interface_override("modbus:meter") is False
    assert await restarted.load_edge_styles() == {}
    assert await restarted.load_interface_overrides() == {}
