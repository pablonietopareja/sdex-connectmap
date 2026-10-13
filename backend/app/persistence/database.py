from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from app.core.errors import ConfigurationError, ResourceNotFoundError, TopologyConflictError
from app.core.security import CredentialCipher
from app.models.schemas import (
    ConnectionInterfaceOverride,
    ConnectionNode,
    ConnectionProfile,
    DeviceVisualRouting,
    DisplaySettings,
    EdgeRoute,
    EdgeRouteUpdate,
    EdgeVisualStyle,
    EdgeVisualStyleUpdate,
    EdgeWaypoint,
    LayoutPosition,
    LayoutState,
    ManualNetworkAddress,
    ManualNetworkInterface,
    Position,
    RackMembership,
    SettingsUpdate,
    TopologySnapshot,
    Viewport,
    VisualElement,
    VisualLink,
    VisualTopologyState,
)

SCHEMA_VERSION = 5
TRANSITIONAL_SCHEMA_VERSION = 6
EDGE_STYLE_SCHEMA_VERSION = 2
VISUAL_TOPOLOGY_SCHEMA_VERSION = 1
CURRENT_LAYOUT_VISUAL_VERSION = 2
T = TypeVar("T")
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Database:
    """Small, explicit SQLite persistence layer.

    Connections are short lived and all operations are serialized through one
    asynchronous lock. This keeps SQLite access deterministic without adding a
    native async driver.
    """

    def __init__(
        self,
        path: Path,
        cipher: CredentialCipher,
        default_refresh_seconds: int = 300,
    ) -> None:
        self.path = path
        self.cipher = cipher
        self.default_refresh_seconds = default_refresh_seconds
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    async def _run(self, operation: Callable[[], T]) -> T:
        async with self._lock:
            return await asyncio.to_thread(operation)

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        def operation() -> None:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_metadata (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        version INTEGER NOT NULL,
                        migrated_at TEXT NOT NULL
                    )
                    """
                )
                schema_row = connection.execute(
                    "SELECT version FROM schema_metadata WHERE singleton=1"
                ).fetchone()
                stored_version = int(schema_row["version"]) if schema_row else None
                transitional_v6 = (
                    stored_version == TRANSITIONAL_SCHEMA_VERSION
                    and self._is_transitional_v6_schema(connection)
                )
                if stored_version is not None and (
                    stored_version < 1 or (stored_version > SCHEMA_VERSION and not transitional_v6)
                ):
                    raise ConfigurationError(
                        "Unsupported ConnectMap database schema version "
                        f"{stored_version}; this application supports versions "
                        f"1 through {SCHEMA_VERSION}."
                    )
                connection.execute("BEGIN IMMEDIATE")
                self._create_core_tables(connection)
                self._create_version_two_tables(connection)
                self._migrate_version_three(connection)
                self._create_version_four_tables(connection)
                self._create_version_five_tables(connection)
                self._repair_visual_link_handles(connection)
                if stored_version is None:
                    connection.execute(
                        """
                        INSERT INTO schema_metadata(singleton, version, migrated_at)
                        VALUES (1, ?, ?)
                        """,
                        (SCHEMA_VERSION, utc_now().isoformat()),
                    )
                    layout_visual_version = CURRENT_LAYOUT_VISUAL_VERSION
                else:
                    if stored_version < SCHEMA_VERSION:
                        connection.execute(
                            """
                            UPDATE schema_metadata
                            SET version=?, migrated_at=?
                            WHERE singleton=1
                            """,
                            (SCHEMA_VERSION, utc_now().isoformat()),
                        )
                    # Existing production positions are retained and explicitly
                    # marked as v1 so the UI can offer a deliberate reset.
                    layout_visual_version = (
                        1 if stored_version == 1 else CURRENT_LAYOUT_VISUAL_VERSION
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO layout_metadata(
                        singleton, visual_version, updated_at
                    ) VALUES (1, ?, ?)
                    """,
                    (layout_visual_version, utc_now().isoformat()),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO display_settings(
                        singleton, refresh_interval_seconds, show_not_enabled, theme, updated_at
                    ) VALUES (1, ?, 0, 'system', ?)
                    """,
                    (self.default_refresh_seconds, utc_now().isoformat()),
                )
                connection.commit()
                if stored_version is not None and stored_version < SCHEMA_VERSION:
                    logger.info(
                        "ConnectMap database schema migration completed",
                        extra={
                            "event": "database_migrated",
                            "status": f"v{stored_version}-to-v{SCHEMA_VERSION}",
                        },
                    )
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

        await self._run(operation)

    @staticmethod
    def _is_transitional_v6_schema(connection: sqlite3.Connection) -> bool:
        """Recognize only the short-lived local v6 schema already written by ConnectMap."""

        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(primary_visual_route)").fetchall()
        }
        return {
            "connection_id",
            "target_element_id",
            "source_handle",
            "target_handle",
            "external_interface",
            "unresolved_interface_confirmed",
            "schema_version",
            "created_at",
            "updated_at",
        } <= columns

    @staticmethod
    def _create_core_tables(connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS connection_profile (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                base_url TEXT NOT NULL,
                username TEXT NOT NULL,
                encrypted_password TEXT NOT NULL,
                verify_tls INTEGER NOT NULL,
                timeout_seconds REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS display_settings (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                refresh_interval_seconds INTEGER NOT NULL,
                show_not_enabled INTEGER NOT NULL DEFAULT 0,
                theme TEXT NOT NULL DEFAULT 'system',
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS node_layout (
                node_id TEXT PRIMARY KEY,
                x REAL NOT NULL,
                y REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS viewport (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                x REAL NOT NULL,
                y REAL NOT NULL,
                zoom REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS topology_snapshot (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                payload TEXT NOT NULL,
                last_success_at TEXT,
                updated_at TEXT NOT NULL
            )
            """,
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _repair_visual_link_handles(connection: sqlite3.Connection) -> None:
        """Replace legacy React Flow placeholder handles with stable per-link IDs."""
        rows = connection.execute(
            """
            SELECT link_id, source_handle, target_handle
            FROM topology_link
            WHERE source_handle IN ('left:new', 'right:new')
               OR target_handle IN ('left:new', 'right:new')
            """
        ).fetchall()
        for row in rows:
            link_id = str(row["link_id"])
            source_handle = row["source_handle"]
            target_handle = row["target_handle"]
            if source_handle in {"left:new", "right:new"}:
                source_handle = f"{str(source_handle).split(':', 1)[0]}:{link_id}"
            if target_handle in {"left:new", "right:new"}:
                target_handle = f"{str(target_handle).split(':', 1)[0]}:{link_id}"
            connection.execute(
                """
                UPDATE topology_link
                SET source_handle=?, target_handle=?
                WHERE link_id=?
                """,
                (source_handle, target_handle, link_id),
            )

    @staticmethod
    def _create_version_two_tables(connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS edge_visual_style (
                edge_id TEXT PRIMARY KEY,
                sheath_color TEXT NOT NULL
                    CHECK (
                        length(sheath_color) = 7
                        AND substr(sheath_color, 1, 1) = '#'
                        AND substr(sheath_color, 2) NOT GLOB '*[^0-9A-F]*'
                    ),
                flow_color TEXT NOT NULL
                    CHECK (
                        length(flow_color) = 7
                        AND substr(flow_color, 1, 1) = '#'
                        AND substr(flow_color, 2) NOT GLOB '*[^0-9A-F]*'
                    ),
                reverse_flow INTEGER NOT NULL DEFAULT 0
                    CHECK (reverse_flow IN (0, 1)),
                schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS connection_interface_override (
                connection_id TEXT PRIMARY KEY,
                interface_name TEXT NOT NULL CHECK (interface_name IN ('eth1', 'eth2')),
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS manual_network_interface (
                interface_name TEXT NOT NULL CHECK (interface_name IN ('eth1', 'eth2')),
                address TEXT NOT NULL,
                prefix_length INTEGER NOT NULL CHECK (prefix_length BETWEEN 0 AND 128),
                ip_version INTEGER NOT NULL CHECK (ip_version IN (4, 6)),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(interface_name, address, prefix_length)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS layout_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                visual_version INTEGER NOT NULL CHECK (visual_version >= 1),
                updated_at TEXT NOT NULL
            )
            """,
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _migrate_version_three(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(edge_visual_style)").fetchall()
        }
        if "reverse_flow" not in columns:
            connection.execute(
                """
                ALTER TABLE edge_visual_style
                ADD COLUMN reverse_flow INTEGER NOT NULL DEFAULT 0
                    CHECK (reverse_flow IN (0, 1))
                """
            )

    @staticmethod
    def _create_version_four_tables(connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS topology_element (
                element_id TEXT PRIMARY KEY CHECK (length(element_id) BETWEEN 8 AND 80),
                element_type TEXT NOT NULL CHECK (element_type IN ('rack', 'switch')),
                name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
                description TEXT CHECK (description IS NULL OR length(description) <= 500),
                x REAL NOT NULL CHECK (x BETWEEN -1000000 AND 1000000),
                y REAL NOT NULL CHECK (y BETWEEN -1000000 AND 1000000),
                width REAL NOT NULL CHECK (width BETWEEN 120 AND 20000),
                height REAL NOT NULL CHECK (height BETWEEN 100 AND 20000),
                rows INTEGER CHECK (rows IS NULL OR rows BETWEEN 1 AND 10),
                columns INTEGER CHECK (columns IS NULL OR columns BETWEEN 1 AND 10),
                collapsed INTEGER NOT NULL DEFAULT 0 CHECK (collapsed IN (0, 1)),
                external_interface TEXT CHECK (
                    external_interface IS NULL OR external_interface IN ('eth1', 'eth2')
                ),
                status_mode TEXT NOT NULL DEFAULT 'neutral'
                    CHECK (status_mode IN ('neutral', 'aggregate')),
                schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (
                    (element_type = 'rack' AND rows IS NOT NULL AND columns IS NOT NULL)
                    OR
                    (element_type = 'switch' AND rows IS NULL AND columns IS NULL)
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS rack_membership (
                rack_id TEXT NOT NULL REFERENCES topology_element(element_id) ON DELETE CASCADE,
                connection_id TEXT NOT NULL UNIQUE,
                slot_row INTEGER NOT NULL CHECK (slot_row BETWEEN 0 AND 9),
                slot_column INTEGER NOT NULL CHECK (slot_column BETWEEN 0 AND 9),
                unresolved_interface_confirmed INTEGER NOT NULL DEFAULT 0
                    CHECK (unresolved_interface_confirmed IN (0, 1)),
                cached_display_name TEXT NOT NULL,
                cached_connection_type TEXT NOT NULL,
                cached_subtype TEXT,
                cached_icon TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (rack_id, connection_id),
                UNIQUE (rack_id, slot_row, slot_column)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS topology_link (
                link_id TEXT PRIMARY KEY CHECK (length(link_id) BETWEEN 13 AND 80),
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                source_element_id TEXT REFERENCES topology_element(element_id) ON DELETE CASCADE,
                target_element_id TEXT REFERENCES topology_element(element_id) ON DELETE CASCADE,
                source_handle TEXT,
                target_handle TEXT,
                external_interface TEXT CHECK (
                    external_interface IS NULL OR external_interface IN ('eth1', 'eth2')
                ),
                unresolved_interface_confirmed INTEGER NOT NULL DEFAULT 0
                    CHECK (unresolved_interface_confirmed IN (0, 1)),
                schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (source_id <> target_id),
                CHECK (source_element_id IS NULL OR source_element_id = source_id),
                CHECK (target_element_id IS NULL OR target_element_id = target_id),
                UNIQUE (source_id, target_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS visual_route_suppression (
                connection_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL CHECK (reason IN ('user_unrouted')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS edge_route (
                edge_id TEXT PRIMARY KEY,
                visual_link_id TEXT UNIQUE REFERENCES topology_link(link_id) ON DELETE CASCADE,
                routing_mode TEXT NOT NULL CHECK (routing_mode IN ('manual', 'orthogonal')),
                schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS edge_waypoint (
                edge_id TEXT NOT NULL REFERENCES edge_route(edge_id) ON DELETE CASCADE,
                waypoint_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 63),
                x REAL NOT NULL CHECK (x BETWEEN -1000000 AND 1000000),
                y REAL NOT NULL CHECK (y BETWEEN -1000000 AND 1000000),
                kind TEXT NOT NULL CHECK (kind IN ('free', 'corner')),
                PRIMARY KEY (edge_id, waypoint_id),
                UNIQUE (edge_id, ordinal)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_rack_membership_rack ON rack_membership(rack_id)",
            "CREATE INDEX IF NOT EXISTS ix_topology_link_source ON topology_link(source_id)",
            "CREATE INDEX IF NOT EXISTS ix_topology_link_target ON topology_link(target_id)",
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _create_version_five_tables(connection: sqlite3.Connection) -> None:
        """Persist local-only routing preferences without coupling them to discovery rows."""

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_visual_routing (
                connection_id TEXT PRIMARY KEY
                    CHECK (length(connection_id) BETWEEN 1 AND 300),
                preferred_source_handle TEXT NOT NULL
                    CHECK (preferred_source_handle IN ('top', 'right', 'bottom', 'left')),
                updated_at TEXT NOT NULL
            )
            """
        )

    async def ping(self) -> bool:
        def operation() -> bool:
            try:
                with self._connect() as connection:
                    result = connection.execute("SELECT 1").fetchone()
                    return bool(result and result[0] == 1)
            except sqlite3.Error:
                return False

        return await self._run(operation)

    async def schema_version(self) -> int:
        def operation() -> int:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT version FROM schema_metadata WHERE singleton=1"
                ).fetchone()
                return int(row["version"]) if row else 0

        return await self._run(operation)

    async def save_profile(self, profile: ConnectionProfile) -> None:
        encrypted_password = self.cipher.encrypt(profile.password.get_secret_value())
        updated_at = utc_now().isoformat()

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO connection_profile(
                        singleton, base_url, username, encrypted_password,
                        verify_tls, timeout_seconds, updated_at
                    ) VALUES (1, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        base_url=excluded.base_url,
                        username=excluded.username,
                        encrypted_password=excluded.encrypted_password,
                        verify_tls=excluded.verify_tls,
                        timeout_seconds=excluded.timeout_seconds,
                        updated_at=excluded.updated_at
                    """,
                    (
                        profile.base_url,
                        profile.username,
                        encrypted_password,
                        int(profile.verify_tls),
                        profile.timeout_seconds,
                        updated_at,
                    ),
                )

        await self._run(operation)

    async def load_profile(self) -> ConnectionProfile | None:
        def operation() -> dict[str, Any] | None:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT base_url, username, encrypted_password, verify_tls, timeout_seconds
                    FROM connection_profile WHERE singleton=1
                    """
                ).fetchone()
                return dict(row) if row else None

        row = await self._run(operation)
        if row is None:
            return None
        password = self.cipher.decrypt(row.pop("encrypted_password"))
        row["verify_tls"] = bool(row["verify_tls"])
        return ConnectionProfile(
            **row,
            password=password,
            source="database",
        )

    async def has_profile(self) -> bool:
        def operation() -> bool:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM connection_profile WHERE singleton=1"
                ).fetchone()
                return row is not None

        return await self._run(operation)

    async def load_settings(self) -> DisplaySettings:
        def operation() -> tuple[dict[str, Any] | None, list[ManualNetworkInterface]]:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT refresh_interval_seconds, show_not_enabled, theme
                    FROM display_settings WHERE singleton=1
                    """
                ).fetchone()
                return (
                    dict(row) if row else None,
                    self._load_manual_network_interfaces(connection),
                )

        row, network_interfaces = await self._run(operation)
        if not row:
            return DisplaySettings(
                refresh_interval_seconds=self.default_refresh_seconds,
                network_interfaces=network_interfaces,
            )
        row["show_not_enabled"] = bool(row["show_not_enabled"])
        row["network_interfaces"] = network_interfaces
        return DisplaySettings(**row)

    async def update_settings(self, update: SettingsUpdate) -> DisplaySettings:
        changes = update.model_dump(exclude_none=True)
        requested_network_interfaces = changes.pop("network_interfaces", None)

        def operation() -> DisplaySettings:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT refresh_interval_seconds, show_not_enabled, theme
                    FROM display_settings WHERE singleton=1
                    """
                ).fetchone()
                if row is None:
                    current = DisplaySettings(
                        refresh_interval_seconds=self.default_refresh_seconds,
                        network_interfaces=self._load_manual_network_interfaces(connection),
                    )
                else:
                    current_values = dict(row)
                    current_values["show_not_enabled"] = bool(current_values["show_not_enabled"])
                    current_values["network_interfaces"] = self._load_manual_network_interfaces(
                        connection
                    )
                    current = DisplaySettings(**current_values)
                values = current.model_dump()
                values.update(changes)
                if requested_network_interfaces is not None:
                    values["network_interfaces"] = requested_network_interfaces
                values.pop("allowed_refresh_intervals", None)
                updated = DisplaySettings(**values)
                connection.execute(
                    """
                    INSERT INTO display_settings(
                        singleton, refresh_interval_seconds, show_not_enabled, theme, updated_at
                    ) VALUES (1, ?, ?, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        refresh_interval_seconds=excluded.refresh_interval_seconds,
                        show_not_enabled=excluded.show_not_enabled,
                        theme=excluded.theme,
                        updated_at=excluded.updated_at
                    """,
                    (
                        updated.refresh_interval_seconds,
                        int(updated.show_not_enabled),
                        updated.theme,
                        utc_now().isoformat(),
                    ),
                )
                if requested_network_interfaces is not None:
                    self._replace_manual_network_interfaces(
                        connection,
                        updated.network_interfaces,
                    )
                return updated

        return await self._run(operation)

    @staticmethod
    def _load_manual_network_interfaces(
        connection: sqlite3.Connection,
    ) -> list[ManualNetworkInterface]:
        rows = connection.execute(
            """
            SELECT interface_name, address, prefix_length
            FROM manual_network_interface
            ORDER BY interface_name, ip_version, address, prefix_length
            """
        ).fetchall()
        grouped: dict[str, list[ManualNetworkAddress]] = {}
        for row in rows:
            grouped.setdefault(str(row["interface_name"]), []).append(
                ManualNetworkAddress(
                    address=str(row["address"]),
                    prefix_length=int(row["prefix_length"]),
                )
            )
        return [
            ManualNetworkInterface(name=name, addresses=addresses)
            for name, addresses in grouped.items()
        ]

    @staticmethod
    def _replace_manual_network_interfaces(
        connection: sqlite3.Connection,
        interfaces: Sequence[ManualNetworkInterface],
    ) -> None:
        connection.execute("DELETE FROM manual_network_interface")
        timestamp = utc_now().isoformat()
        rows = [
            (
                interface.name,
                address.address,
                address.prefix_length,
                6 if ":" in address.address else 4,
                timestamp,
            )
            for interface in interfaces
            for address in interface.addresses
        ]
        if rows:
            connection.executemany(
                """
                INSERT INTO manual_network_interface(
                    interface_name, address, prefix_length, ip_version, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

    async def load_manual_network_interfaces(self) -> list[ManualNetworkInterface]:
        def operation() -> list[ManualNetworkInterface]:
            with self._connect() as connection:
                return self._load_manual_network_interfaces(connection)

        return await self._run(operation)

    async def save_edge_style(
        self,
        edge_id: str,
        update: EdgeVisualStyleUpdate,
    ) -> EdgeVisualStyle:
        style = EdgeVisualStyle(
            edge_id=edge_id,
            sheath_color=update.sheath_color,
            flow_color=update.flow_color,
            reverse_flow=update.reverse_flow,
            updated_at=utc_now(),
            schema_version=EDGE_STYLE_SCHEMA_VERSION,
        )

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO edge_visual_style(
                        edge_id, sheath_color, flow_color, reverse_flow,
                        schema_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(edge_id) DO UPDATE SET
                        sheath_color=excluded.sheath_color,
                        flow_color=excluded.flow_color,
                        reverse_flow=excluded.reverse_flow,
                        schema_version=excluded.schema_version,
                        updated_at=excluded.updated_at
                    """,
                    (
                        style.edge_id,
                        style.sheath_color,
                        style.flow_color,
                        int(style.reverse_flow),
                        style.schema_version,
                        style.updated_at.isoformat(),
                    ),
                )

        await self._run(operation)
        return style

    async def delete_edge_style(self, edge_id: str) -> bool:
        def operation() -> bool:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM edge_visual_style WHERE edge_id=?",
                    (edge_id,),
                )
                return cursor.rowcount > 0

        return await self._run(operation)

    async def load_edge_styles(self) -> dict[str, EdgeVisualStyle]:
        def operation() -> list[dict[str, Any]]:
            with self._connect() as connection:
                return [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT edge_id, sheath_color, flow_color, reverse_flow,
                               updated_at, schema_version
                        FROM edge_visual_style
                        """
                    ).fetchall()
                ]

        rows = await self._run(operation)
        for row in rows:
            row["reverse_flow"] = bool(row["reverse_flow"])
        return {str(row["edge_id"]): EdgeVisualStyle(**row) for row in rows}

    async def save_device_visual_routing(
        self,
        connection_id: str,
        preferred_source_handle: str,
    ) -> DeviceVisualRouting:
        routing = DeviceVisualRouting(
            connection_id=connection_id,
            preferred_source_handle=preferred_source_handle,
            updated_at=utc_now(),
        )

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO device_visual_routing(
                        connection_id, preferred_source_handle, updated_at
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(connection_id) DO UPDATE SET
                        preferred_source_handle=excluded.preferred_source_handle,
                        updated_at=excluded.updated_at
                    """,
                    (
                        routing.connection_id,
                        routing.preferred_source_handle,
                        routing.updated_at.isoformat(),
                    ),
                )

        await self._run(operation)
        return routing

    async def load_device_visual_routings(self) -> dict[str, DeviceVisualRouting]:
        def operation() -> list[dict[str, Any]]:
            with self._connect() as connection:
                return [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT connection_id, preferred_source_handle, updated_at
                        FROM device_visual_routing
                        ORDER BY connection_id
                        """
                    ).fetchall()
                ]

        rows = await self._run(operation)
        return {str(row["connection_id"]): DeviceVisualRouting(**row) for row in rows}

    async def delete_device_visual_routing(self, connection_id: str) -> bool:
        def operation() -> bool:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM device_visual_routing WHERE connection_id=?",
                    (connection_id,),
                )
                return cursor.rowcount > 0

        return await self._run(operation)

    async def load_visual_topology(self) -> VisualTopologyState:
        def operation() -> tuple[
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[str],
        ]:
            with self._connect() as connection:
                self._repair_visual_link_handles(connection)
                elements = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM topology_element ORDER BY created_at, element_id"
                    ).fetchall()
                ]
                memberships = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT * FROM rack_membership
                        ORDER BY rack_id, slot_row, slot_column, connection_id
                        """
                    ).fetchall()
                ]
                links = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM topology_link ORDER BY created_at, link_id"
                    ).fetchall()
                ]
                routes = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM edge_route ORDER BY edge_id"
                    ).fetchall()
                ]
                waypoints = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM edge_waypoint ORDER BY edge_id, ordinal"
                    ).fetchall()
                ]
                suppressions = [
                    str(row["connection_id"])
                    for row in connection.execute(
                        """
                        SELECT connection_id FROM visual_route_suppression
                        ORDER BY connection_id
                        """
                    ).fetchall()
                ]
                return (
                    elements,
                    memberships,
                    links,
                    routes,
                    waypoints,
                    suppressions,
                )

        (
            element_rows,
            member_rows,
            link_rows,
            route_rows,
            waypoint_rows,
            suppressions,
        ) = await self._run(operation)
        elements = []
        for row in element_rows:
            elements.append(
                VisualElement(
                    id=row["element_id"],
                    type=row["element_type"],
                    name=row["name"],
                    description=row["description"],
                    position=Position(x=row["x"], y=row["y"]),
                    width=row["width"],
                    height=row["height"],
                    rows=row["rows"],
                    columns=row["columns"],
                    collapsed=bool(row["collapsed"]),
                    external_interface=row["external_interface"],
                    status_mode=row["status_mode"],
                    schema_version=row["schema_version"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )
        memberships = [
            RackMembership(
                rack_id=row["rack_id"],
                connection_id=row["connection_id"],
                row=row["slot_row"],
                column=row["slot_column"],
                missing=True,
                unresolved_interface_confirmed=bool(row["unresolved_interface_confirmed"]),
                cached_display_name=row["cached_display_name"],
                cached_connection_type=row["cached_connection_type"],
                cached_subtype=row["cached_subtype"],
                cached_icon=row["cached_icon"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in member_rows
        ]
        links = [
            VisualLink(
                id=row["link_id"],
                source=row["source_id"],
                target=row["target_id"],
                source_handle=row["source_handle"],
                target_handle=row["target_handle"],
                external_interface=row["external_interface"],
                unresolved_interface_confirmed=bool(row["unresolved_interface_confirmed"]),
                schema_version=row["schema_version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in link_rows
        ]
        points_by_edge: dict[str, list[EdgeWaypoint]] = {}
        for row in waypoint_rows:
            points_by_edge.setdefault(str(row["edge_id"]), []).append(
                EdgeWaypoint(
                    id=row["waypoint_id"],
                    x=row["x"],
                    y=row["y"],
                    kind=row["kind"],
                    order=row["ordinal"],
                )
            )
        routes = {
            str(row["edge_id"]): EdgeRoute(
                edge_id=row["edge_id"],
                routing_mode=row["routing_mode"],
                waypoints=points_by_edge.get(str(row["edge_id"]), []),
                schema_version=row["schema_version"],
                updated_at=row["updated_at"],
            )
            for row in route_rows
        }
        return VisualTopologyState(
            elements=elements,
            rack_memberships=memberships,
            links=links,
            routes=routes,
            unrouted_connection_ids=suppressions,
        )

    @staticmethod
    def _upsert_visual_element(
        connection: sqlite3.Connection,
        element: VisualElement,
    ) -> None:
        connection.execute(
            """
            INSERT INTO topology_element(
                element_id, element_type, name, description, x, y, width, height,
                rows, columns, collapsed, external_interface, status_mode,
                schema_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(element_id) DO UPDATE SET
                name=excluded.name, description=excluded.description,
                x=excluded.x, y=excluded.y, width=excluded.width,
                height=excluded.height, rows=excluded.rows, columns=excluded.columns,
                collapsed=excluded.collapsed,
                external_interface=excluded.external_interface,
                status_mode=excluded.status_mode,
                schema_version=excluded.schema_version,
                updated_at=excluded.updated_at
            """,
            (
                element.id,
                str(element.type),
                element.name,
                element.description,
                element.position.x,
                element.position.y,
                element.width,
                element.height,
                element.rows,
                element.columns,
                int(element.collapsed),
                element.external_interface,
                element.status_mode,
                element.schema_version,
                element.created_at.isoformat(),
                element.updated_at.isoformat(),
            ),
        )

    async def save_visual_element(self, element: VisualElement) -> VisualElement:
        def operation() -> None:
            with self._connect() as connection:
                self._upsert_visual_element(connection, element)

        await self._run(operation)
        return element

    async def update_visual_element(
        self,
        element: VisualElement,
        *,
        eject_overflow: bool,
    ) -> list[str]:
        """Update an element and eject any invalid Rack slots in one transaction."""

        def operation() -> list[str]:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    """
                    SELECT element_type FROM topology_element
                    WHERE element_id=?
                    """,
                    (element.id,),
                ).fetchone()
                if current is None:
                    raise ResourceNotFoundError()

                members = connection.execute(
                    """
                    SELECT connection_id, slot_row, slot_column
                    FROM rack_membership
                    WHERE rack_id=?
                    ORDER BY slot_row, slot_column, connection_id
                    """,
                    (element.id,),
                ).fetchall()
                if members and element.external_interface is None:
                    raise TopologyConflictError(
                        "A Rack with members must keep one external interface."
                    )
                overflow = [
                    row
                    for row in members
                    if element.rows is not None
                    and element.columns is not None
                    and (
                        int(row["slot_row"]) >= element.rows
                        or int(row["slot_column"]) >= element.columns
                    )
                ]
                if overflow and not eject_overflow:
                    raise TopologyConflictError(
                        "The requested rack matrix would evict existing members.",
                        details={
                            "overflow_member_ids": [str(row["connection_id"]) for row in overflow]
                        },
                    )

                incompatible_links = []
                if str(current["element_type"]) == "rack":
                    incompatible_links = [
                        str(row["link_id"])
                        for row in connection.execute(
                            """
                            SELECT link_id FROM topology_link
                            WHERE (source_id=? OR target_id=?)
                              AND external_interface IS NOT NULL
                              AND external_interface IS NOT ?
                            """,
                            (element.id, element.id, element.external_interface),
                        ).fetchall()
                    ]
                if incompatible_links:
                    raise TopologyConflictError(
                        "Existing visual links use a different SDEX interface.",
                        details={"incompatible_link_ids": incompatible_links},
                    )

                overflow_ids = [str(row["connection_id"]) for row in overflow]
                if overflow_ids:
                    connection.executemany(
                        """
                        DELETE FROM rack_membership
                        WHERE rack_id=? AND connection_id=?
                        """,
                        [(element.id, connection_id) for connection_id in overflow_ids],
                    )
                self._upsert_visual_element(connection, element)
                if overflow_ids:
                    self._persist_ejected_layout(connection, element, overflow_ids)
                return overflow_ids

        return await self._run(operation)

    @staticmethod
    def _persist_ejected_layout(
        connection: sqlite3.Connection,
        rack: VisualElement,
        connection_ids: Sequence[str],
    ) -> None:
        """Place ejected cards beside a Rack without overlapping one another."""
        timestamp = utc_now().isoformat()
        base_x = rack.position.x + rack.width + 64.0
        base_y = rack.position.y
        card_width = 370.0
        card_height = 220.0
        horizontal_clearance = 18.0
        vertical_clearance = 18.0
        vertical_step = 248.0
        ejected_ids = set(connection_ids)
        occupied = [
            (float(row["x"]), float(row["y"]), card_width, card_height)
            for row in connection.execute("SELECT node_id, x, y FROM node_layout").fetchall()
            if str(row["node_id"]) not in ejected_ids
        ]
        occupied.extend(
            (
                float(row["x"]),
                float(row["y"]),
                float(row["width"]),
                float(row["height"]),
            )
            for row in connection.execute(
                """
                SELECT x, y, width, height FROM topology_element
                WHERE element_id<>?
                """,
                (rack.id,),
            ).fetchall()
        )
        positions: list[tuple[str, float, float, str]] = []
        for index, connection_id in enumerate(connection_ids):
            x = base_x
            y = base_y + index * vertical_step
            while any(
                x < other_x + other_width + horizontal_clearance
                and x + card_width + horizontal_clearance > other_x
                and y < other_y + other_height + vertical_clearance
                and y + card_height + vertical_clearance > other_y
                for other_x, other_y, other_width, other_height in occupied
            ):
                y += vertical_step
            occupied.append((x, y, card_width, card_height))
            positions.append((connection_id, x, y, timestamp))
        connection.executemany(
            """
            INSERT INTO node_layout(node_id, x, y, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                x=excluded.x, y=excluded.y, updated_at=excluded.updated_at
            """,
            positions,
        )

    @staticmethod
    def _copy_edge_presentation(
        connection: sqlite3.Connection,
        source_edge_id: str,
        target_edge_id: str,
    ) -> None:
        style = connection.execute(
            "SELECT * FROM edge_visual_style WHERE edge_id=?",
            (source_edge_id,),
        ).fetchone()
        if style is not None:
            connection.execute(
                """
                INSERT INTO edge_visual_style(
                    edge_id, sheath_color, flow_color, reverse_flow,
                    schema_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET
                    sheath_color=excluded.sheath_color,
                    flow_color=excluded.flow_color,
                    reverse_flow=excluded.reverse_flow,
                    schema_version=excluded.schema_version,
                    updated_at=excluded.updated_at
                """,
                (
                    target_edge_id,
                    style["sheath_color"],
                    style["flow_color"],
                    style["reverse_flow"],
                    style["schema_version"],
                    style["updated_at"],
                ),
            )
        route = connection.execute(
            "SELECT * FROM edge_route WHERE edge_id=?",
            (source_edge_id,),
        ).fetchone()
        if route is None:
            return
        points = connection.execute(
            """
            SELECT waypoint_id, ordinal, x, y, kind
            FROM edge_waypoint WHERE edge_id=? ORDER BY ordinal
            """,
            (source_edge_id,),
        ).fetchall()
        connection.execute(
            """
            INSERT INTO edge_route(
                edge_id, visual_link_id, routing_mode, schema_version, updated_at
            ) VALUES (?, NULL, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                visual_link_id=NULL,
                routing_mode=excluded.routing_mode,
                schema_version=excluded.schema_version,
                updated_at=excluded.updated_at
            """,
            (
                target_edge_id,
                route["routing_mode"],
                route["schema_version"],
                route["updated_at"],
            ),
        )
        connection.execute("DELETE FROM edge_waypoint WHERE edge_id=?", (target_edge_id,))
        connection.executemany(
            """
            INSERT INTO edge_waypoint(edge_id, waypoint_id, ordinal, x, y, kind)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    target_edge_id,
                    point["waypoint_id"],
                    point["ordinal"],
                    point["x"],
                    point["y"],
                    point["kind"],
                )
                for point in points
            ],
        )

    async def delete_visual_element(
        self,
        element_id: str,
        *,
        gateway_id: str | None = None,
        eject_members: bool = False,
        leave_unrouted: bool = False,
    ) -> tuple[bool, list[str], list[str], list[str]]:
        def operation() -> tuple[bool, list[str], list[str], list[str]]:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                element = connection.execute(
                    "SELECT element_type FROM topology_element WHERE element_id=?",
                    (element_id,),
                ).fetchone()
                if element is None:
                    return False, [], [], []
                member_ids = [
                    str(row["connection_id"])
                    for row in connection.execute(
                        "SELECT connection_id FROM rack_membership WHERE rack_id=?",
                        (element_id,),
                    ).fetchall()
                ]
                if member_ids and not eject_members:
                    raise TopologyConflictError(
                        "The Rack contains members; explicit ejection is required.",
                        details={"member_ids": member_ids},
                    )
                link_rows = connection.execute(
                    """
                    SELECT * FROM topology_link
                    WHERE source_id=? OR target_id=?
                    ORDER BY created_at, link_id
                    """,
                    (element_id, element_id),
                ).fetchall()
                link_ids = [str(row["link_id"]) for row in link_rows]
                incoming_source_ids = [
                    str(row["source_id"])
                    for row in link_rows
                    if row["target_id"] == element_id
                    if not str(row["source_id"]).startswith(("rack:", "switch:"))
                ]
                retained_link_ids: set[str] = set()
                if (
                    str(element["element_type"]) == "switch"
                    and gateway_id is not None
                    and not leave_unrouted
                ):
                    timestamp = utc_now().isoformat()
                    for row in link_rows:
                        if row["target_id"] != element_id:
                            continue
                        link_id = str(row["link_id"])
                        source_id = str(row["source_id"])
                        if source_id.startswith(("rack:", "switch:")):
                            target_handle = (
                                f"sdex-{row['external_interface']}"
                                if row["external_interface"] is not None
                                else None
                            )
                            connection.execute(
                                """
                                UPDATE topology_link
                                SET target_id=?, target_element_id=NULL,
                                    target_handle=?, updated_at=?
                                WHERE link_id=?
                                """,
                                (gateway_id, target_handle, timestamp, link_id),
                            )
                            retained_link_ids.add(link_id)
                        else:
                            self._copy_edge_presentation(
                                connection,
                                link_id,
                                f"sdex-to-{source_id}",
                            )
                deleted_link_ids = [
                    link_id for link_id in link_ids if link_id not in retained_link_ids
                ]
                if deleted_link_ids:
                    connection.executemany(
                        "DELETE FROM edge_visual_style WHERE edge_id=?",
                        [(link_id,) for link_id in deleted_link_ids],
                    )
                cursor = connection.execute(
                    "DELETE FROM topology_element WHERE element_id=?",
                    (element_id,),
                )
                if leave_unrouted:
                    now = utc_now().isoformat()
                    connection.executemany(
                        """
                        INSERT INTO visual_route_suppression(
                            connection_id, reason, created_at, updated_at
                        ) VALUES (?, 'user_unrouted', ?, ?)
                        ON CONFLICT(connection_id) DO UPDATE SET updated_at=excluded.updated_at
                        """,
                        [(source_id, now, now) for source_id in incoming_source_ids],
                    )
                return (
                    cursor.rowcount > 0,
                    member_ids,
                    link_ids,
                    incoming_source_ids if leave_unrouted else [],
                )

        return await self._run(operation)

    @staticmethod
    def _upsert_rack_membership(
        connection: sqlite3.Connection,
        rack_id: str,
        node: ConnectionNode,
        row: int,
        column: int,
        *,
        unresolved_interface_confirmed: bool,
        now: datetime,
    ) -> str:
        existing = connection.execute(
            """
            SELECT created_at FROM rack_membership
            WHERE rack_id=? AND connection_id=?
            """,
            (rack_id, node.id),
        ).fetchone()
        created_at = str(existing["created_at"]) if existing else now.isoformat()
        connection.execute(
            """
            INSERT INTO rack_membership(
                rack_id, connection_id, slot_row, slot_column,
                unresolved_interface_confirmed, cached_display_name,
                cached_connection_type, cached_subtype, cached_icon,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rack_id, connection_id) DO UPDATE SET
                slot_row=excluded.slot_row, slot_column=excluded.slot_column,
                unresolved_interface_confirmed=excluded.unresolved_interface_confirmed,
                cached_display_name=excluded.cached_display_name,
                cached_connection_type=excluded.cached_connection_type,
                cached_subtype=excluded.cached_subtype,
                cached_icon=excluded.cached_icon,
                updated_at=excluded.updated_at
            """,
            (
                rack_id,
                node.id,
                row,
                column,
                int(unresolved_interface_confirmed),
                node.display_name,
                str(node.type),
                node.subtype,
                node.icon,
                created_at,
                now.isoformat(),
            ),
        )
        return created_at

    async def save_rack_membership(
        self,
        rack_id: str,
        node: ConnectionNode,
        row: int,
        column: int,
        *,
        unresolved_interface_confirmed: bool,
        connection_interface: str | None = None,
        validate_interface: bool = False,
        allow_unresolved_interface: bool = False,
    ) -> RackMembership:
        now = utc_now()

        def operation() -> str:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rack = connection.execute(
                    """
                    SELECT element_type, rows, columns, external_interface
                    FROM topology_element WHERE element_id=?
                    """,
                    (rack_id,),
                ).fetchone()
                if rack is None or str(rack["element_type"]) != "rack":
                    raise ResourceNotFoundError()
                if row >= int(rack["rows"]) or column >= int(rack["columns"]):
                    raise TopologyConflictError(
                        "The selected Rack slot is outside the configured matrix."
                    )
                owner = connection.execute(
                    """
                    SELECT rack_id FROM rack_membership
                    WHERE connection_id=? AND rack_id<>?
                    """,
                    (node.id, rack_id),
                ).fetchone()
                if owner is not None:
                    raise TopologyConflictError("A connection can belong to only one Rack.")
                occupant = connection.execute(
                    """
                    SELECT connection_id FROM rack_membership
                    WHERE rack_id=? AND slot_row=? AND slot_column=?
                      AND connection_id<>?
                    """,
                    (rack_id, row, column, node.id),
                ).fetchone()
                if occupant is not None:
                    raise TopologyConflictError("The selected Rack slot is already occupied.")
                linked = connection.execute(
                    "SELECT 1 FROM topology_link WHERE source_id=?",
                    (node.id,),
                ).fetchone()
                if linked is not None:
                    raise TopologyConflictError(
                        "Remove the connection's visual uplink before placing it in a Rack."
                    )
                if validate_interface:
                    rack_interface = rack["external_interface"]
                    if connection_interface is not None:
                        if rack_interface is None:
                            connection.execute(
                                """
                                UPDATE topology_element
                                SET external_interface=?, updated_at=?
                                WHERE element_id=?
                                """,
                                (connection_interface, now.isoformat(), rack_id),
                            )
                        elif str(rack_interface) != connection_interface:
                            raise TopologyConflictError(
                                "The connection and Rack use different SDEX interfaces.",
                                details={
                                    "connection_interface": connection_interface,
                                    "rack_interface": str(rack_interface),
                                },
                            )
                    elif rack_interface is None or not allow_unresolved_interface:
                        raise TopologyConflictError(
                            "The connection interface is unresolved; select a Rack "
                            "interface and confirm it."
                        )
                created_at = self._upsert_rack_membership(
                    connection,
                    rack_id,
                    node,
                    row,
                    column,
                    unresolved_interface_confirmed=unresolved_interface_confirmed,
                    now=now,
                )
                connection.execute(
                    "DELETE FROM visual_route_suppression WHERE connection_id=?",
                    (node.id,),
                )
                return created_at

        created_at = await self._run(operation)
        return RackMembership(
            rack_id=rack_id,
            connection_id=node.id,
            row=row,
            column=column,
            missing=False,
            connection=node,
            unresolved_interface_confirmed=unresolved_interface_confirmed,
            cached_display_name=node.display_name,
            cached_connection_type=str(node.type),
            cached_subtype=node.subtype,
            cached_icon=node.icon,
            created_at=created_at,
            updated_at=now,
        )

    async def delete_rack_membership(self, rack_id: str, connection_id: str) -> bool:
        def operation() -> bool:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM rack_membership WHERE rack_id=? AND connection_id=?",
                    (rack_id, connection_id),
                )
                return cursor.rowcount > 0

        return await self._run(operation)

    @staticmethod
    def _stable_visual_handle(handle: str | None, link_id: str) -> str | None:
        if handle in {"left:new", "right:new"}:
            return f"{handle.split(':', 1)[0]}:{link_id}"
        return handle

    @classmethod
    def _upsert_visual_link(
        cls,
        connection: sqlite3.Connection,
        link: VisualLink,
    ) -> None:
        source_element = link.source if link.source.startswith(("rack:", "switch:")) else None
        target_element = link.target if link.target.startswith(("rack:", "switch:")) else None
        connection.execute(
            """
            INSERT INTO topology_link(
                link_id, source_id, target_id, source_element_id,
                target_element_id, source_handle, target_handle,
                external_interface, unresolved_interface_confirmed,
                schema_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link_id) DO UPDATE SET
                target_id=excluded.target_id,
                target_element_id=excluded.target_element_id,
                source_handle=excluded.source_handle,
                target_handle=excluded.target_handle,
                external_interface=excluded.external_interface,
                unresolved_interface_confirmed=excluded.unresolved_interface_confirmed,
                schema_version=excluded.schema_version,
                updated_at=excluded.updated_at
            """,
            (
                link.id,
                link.source,
                link.target,
                source_element,
                target_element,
                cls._stable_visual_handle(link.source_handle, link.id),
                cls._stable_visual_handle(link.target_handle, link.id),
                link.external_interface,
                int(link.unresolved_interface_confirmed),
                link.schema_version,
                link.created_at.isoformat(),
                link.updated_at.isoformat(),
            ),
        )

    async def save_visual_link(self, link: VisualLink) -> VisualLink:
        def operation() -> None:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                source_element = connection.execute(
                    """
                    SELECT element_type, external_interface FROM topology_element
                    WHERE element_id=?
                    """,
                    (link.source,),
                ).fetchone()
                target_element = connection.execute(
                    """
                    SELECT element_type, external_interface FROM topology_element
                    WHERE element_id=?
                    """,
                    (link.target,),
                ).fetchone()
                if link.source.startswith(("rack:", "switch:")) and source_element is None:
                    raise ResourceNotFoundError()
                if link.target.startswith(("rack:", "switch:")) and target_element is None:
                    raise ResourceNotFoundError()
                if target_element is not None and str(target_element["element_type"]) != "switch":
                    raise TopologyConflictError("Only a Switch or SDEX can be an uplink target.")
                if connection.execute(
                    "SELECT 1 FROM rack_membership WHERE connection_id=?",
                    (link.source,),
                ).fetchone():
                    raise TopologyConflictError(
                        "A Rack member cannot also have an external visual link."
                    )
                if connection.execute(
                    """
                    SELECT 1 FROM topology_link
                    WHERE source_id=? AND link_id<>?
                    """,
                    (link.source, link.id),
                ).fetchone():
                    raise TopologyConflictError("The source already has a visual uplink.")
                if connection.execute(
                    """
                    SELECT 1 FROM topology_link
                    WHERE source_id=? AND target_id=? AND link_id<>?
                    """,
                    (link.target, link.source, link.id),
                ).fetchone():
                    raise TopologyConflictError("That visual link already exists.")

                outgoing = {
                    str(row["source_id"]): str(row["target_id"])
                    for row in connection.execute(
                        "SELECT source_id, target_id FROM topology_link WHERE link_id<>?",
                        (link.id,),
                    ).fetchall()
                }
                outgoing[link.source] = link.target
                cursor = link.target
                visited: set[str] = set()
                while cursor in outgoing:
                    if cursor == link.source or cursor in visited:
                        raise TopologyConflictError("The visual link would create a cycle.")
                    visited.add(cursor)
                    cursor = outgoing[cursor]

                for element_id, element_row in (
                    (link.source, source_element),
                    (link.target, target_element),
                ):
                    if element_row is None or link.external_interface is None:
                        continue
                    # A Switch interface is either an explicit user override or
                    # derived from all descendants. A first child link must not
                    # silently turn its interface into an override, and mixed
                    # descendants must remain representable as a conflict.
                    if str(element_row["element_type"]) == "switch":
                        continue
                    element_interface = element_row["external_interface"]
                    if element_interface is None:
                        connection.execute(
                            """
                            UPDATE topology_element
                            SET external_interface=?, updated_at=?
                            WHERE element_id=?
                            """,
                            (link.external_interface, link.updated_at.isoformat(), element_id),
                        )
                    elif str(element_interface) != link.external_interface:
                        raise TopologyConflictError(
                            "The visual link conflicts with the element's SDEX interface."
                        )

                self._upsert_visual_link(connection, link)
                connection.execute(
                    "DELETE FROM visual_route_suppression WHERE connection_id=?",
                    (link.source,),
                )

        await self._run(operation)
        return link.model_copy(
            update={
                "source_handle": self._stable_visual_handle(link.source_handle, link.id),
                "target_handle": self._stable_visual_handle(link.target_handle, link.id),
            }
        )

    async def delete_visual_link(self, link_id: str, *, leave_unrouted: bool = False) -> bool:
        now = utc_now().isoformat()

        def operation() -> bool:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT source_id FROM topology_link WHERE link_id=?",
                    (link_id,),
                ).fetchone()
                if row is None:
                    return False
                source_id = str(row["source_id"])
                connection.execute("DELETE FROM edge_visual_style WHERE edge_id=?", (link_id,))
                connection.execute("DELETE FROM topology_link WHERE link_id=?", (link_id,))
                if leave_unrouted and not source_id.startswith(("rack:", "switch:")):
                    connection.execute(
                        """
                        INSERT INTO visual_route_suppression(
                            connection_id, reason, created_at, updated_at
                        ) VALUES (?, 'user_unrouted', ?, ?)
                        ON CONFLICT(connection_id) DO UPDATE SET updated_at=excluded.updated_at
                        """,
                        (source_id, now, now),
                    )
                return True

        return await self._run(operation)

    async def seed_visual_topology(
        self,
        elements: Sequence[VisualElement],
        memberships: Sequence[tuple[str, ConnectionNode, int, int, bool]],
        links: Sequence[VisualLink],
        routes: Sequence[tuple[str, EdgeRouteUpdate]],
    ) -> bool:
        """Seed the deterministic editor scenario once, in one transaction."""

        def operation() -> bool:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                has_state = connection.execute(
                    """
                    SELECT EXISTS(SELECT 1 FROM topology_element)
                        OR EXISTS(SELECT 1 FROM rack_membership)
                        OR EXISTS(SELECT 1 FROM topology_link)
                        OR EXISTS(SELECT 1 FROM edge_route)
                        OR EXISTS(SELECT 1 FROM visual_route_suppression)
                    """
                ).fetchone()[0]
                if bool(has_state):
                    return False
                for element in elements:
                    self._upsert_visual_element(connection, element)
                now = utc_now()
                for rack_id, node, row, column, unresolved in memberships:
                    self._upsert_rack_membership(
                        connection,
                        rack_id,
                        node,
                        row,
                        column,
                        unresolved_interface_confirmed=unresolved,
                        now=now,
                    )
                for link in links:
                    self._upsert_visual_link(connection, link)
                    connection.execute(
                        "DELETE FROM visual_route_suppression WHERE connection_id=?",
                        (link.source,),
                    )
                for edge_id, update in routes:
                    normalized_points = [
                        waypoint.model_copy(update={"order": index})
                        for index, waypoint in enumerate(update.waypoints)
                    ]
                    route_now = utc_now().isoformat()
                    visual_link_id = edge_id if edge_id.startswith("visual-link:") else None
                    connection.execute(
                        """
                        INSERT INTO edge_route(
                            edge_id, visual_link_id, routing_mode,
                            schema_version, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            edge_id,
                            visual_link_id,
                            str(update.routing_mode),
                            VISUAL_TOPOLOGY_SCHEMA_VERSION,
                            route_now,
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO edge_waypoint(
                            edge_id, waypoint_id, ordinal, x, y, kind
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                edge_id,
                                waypoint.id,
                                waypoint.order,
                                waypoint.x,
                                waypoint.y,
                                str(waypoint.kind),
                            )
                            for waypoint in normalized_points
                        ],
                    )
                return True

        return await self._run(operation)

    async def save_edge_route(
        self,
        edge_id: str,
        update: EdgeRouteUpdate,
    ) -> EdgeRoute | None:
        if str(update.routing_mode) == "auto":

            def reset_operation() -> None:
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    if (
                        edge_id.startswith("visual-link:")
                        and connection.execute(
                            "SELECT 1 FROM topology_link WHERE link_id=?",
                            (edge_id,),
                        ).fetchone()
                        is None
                    ):
                        raise ResourceNotFoundError()
                    connection.execute("DELETE FROM edge_route WHERE edge_id=?", (edge_id,))

            await self._run(reset_operation)
            return None
        now = utc_now()
        normalized_points = [
            waypoint.model_copy(update={"order": index})
            for index, waypoint in enumerate(update.waypoints)
        ]

        def operation() -> None:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                visual_link_exists = connection.execute(
                    "SELECT 1 FROM topology_link WHERE link_id=?",
                    (edge_id,),
                ).fetchone()
                if edge_id.startswith("visual-link:") and visual_link_exists is None:
                    raise ResourceNotFoundError()
                visual_link_id = edge_id if visual_link_exists is not None else None
                connection.execute(
                    """
                    INSERT INTO edge_route(
                        edge_id, visual_link_id, routing_mode, schema_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(edge_id) DO UPDATE SET
                        visual_link_id=excluded.visual_link_id,
                        routing_mode=excluded.routing_mode,
                        schema_version=excluded.schema_version,
                        updated_at=excluded.updated_at
                    """,
                    (
                        edge_id,
                        visual_link_id,
                        str(update.routing_mode),
                        VISUAL_TOPOLOGY_SCHEMA_VERSION,
                        now.isoformat(),
                    ),
                )
                connection.execute("DELETE FROM edge_waypoint WHERE edge_id=?", (edge_id,))
                connection.executemany(
                    """
                    INSERT INTO edge_waypoint(
                        edge_id, waypoint_id, ordinal, x, y, kind
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            edge_id,
                            waypoint.id,
                            waypoint.order,
                            waypoint.x,
                            waypoint.y,
                            str(waypoint.kind),
                        )
                        for waypoint in normalized_points
                    ],
                )

        await self._run(operation)
        return EdgeRoute(
            edge_id=edge_id,
            routing_mode=update.routing_mode,
            waypoints=normalized_points,
            schema_version=VISUAL_TOPOLOGY_SCHEMA_VERSION,
            updated_at=now,
        )

    async def delete_edge_route(self, edge_id: str) -> bool:
        def operation() -> bool:
            with self._connect() as connection:
                cursor = connection.execute("DELETE FROM edge_route WHERE edge_id=?", (edge_id,))
                return cursor.rowcount > 0

        return await self._run(operation)

    async def save_interface_override(
        self,
        connection_id: str,
        interface_name: str,
    ) -> ConnectionInterfaceOverride:
        override = ConnectionInterfaceOverride(
            connection_id=connection_id,
            interface_name=interface_name,
            updated_at=utc_now(),
        )

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO connection_interface_override(
                        connection_id, interface_name, updated_at
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(connection_id) DO UPDATE SET
                        interface_name=excluded.interface_name,
                        updated_at=excluded.updated_at
                    """,
                    (
                        override.connection_id,
                        override.interface_name,
                        override.updated_at.isoformat(),
                    ),
                )

        await self._run(operation)
        return override

    async def delete_interface_override(self, connection_id: str) -> bool:
        def operation() -> bool:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM connection_interface_override WHERE connection_id=?",
                    (connection_id,),
                )
                return cursor.rowcount > 0

        return await self._run(operation)

    async def load_interface_overrides(
        self,
    ) -> dict[str, ConnectionInterfaceOverride]:
        def operation() -> list[dict[str, Any]]:
            with self._connect() as connection:
                return [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT connection_id, interface_name, updated_at
                        FROM connection_interface_override
                        """
                    ).fetchall()
                ]

        rows = await self._run(operation)
        return {str(row["connection_id"]): ConnectionInterfaceOverride(**row) for row in rows}

    async def save_snapshot(self, snapshot: TopologySnapshot) -> None:
        payload = snapshot.model_dump_json()
        updated_at = utc_now().isoformat()
        success = (
            snapshot.last_successful_refresh.isoformat()
            if snapshot.last_successful_refresh
            else None
        )

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO topology_snapshot(
                        singleton, payload, last_success_at, updated_at
                    ) VALUES (1, ?, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        payload=excluded.payload,
                        last_success_at=excluded.last_success_at,
                        updated_at=excluded.updated_at
                    """,
                    (payload, success, updated_at),
                )

        await self._run(operation)

    async def load_snapshot(self) -> TopologySnapshot | None:
        def operation() -> str | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM topology_snapshot WHERE singleton=1"
                ).fetchone()
                return str(row["payload"]) if row else None

        payload = await self._run(operation)
        if payload is None:
            return None
        try:
            return TopologySnapshot.model_validate_json(payload)
        except (ValueError, json.JSONDecodeError):
            return None

    async def save_layout(
        self,
        positions: Sequence[LayoutPosition],
        viewport: Viewport | None,
    ) -> None:
        timestamp = utc_now().isoformat()

        def operation() -> None:
            with self._connect() as connection:
                if positions:
                    element_ids = {
                        str(row["element_id"])
                        for row in connection.execute(
                            "SELECT element_id FROM topology_element"
                        ).fetchall()
                    }
                    element_positions = [
                        position for position in positions if position.node_id in element_ids
                    ]
                    source_positions = [
                        position for position in positions if position.node_id not in element_ids
                    ]
                    connection.executemany(
                        """
                        INSERT INTO node_layout(node_id, x, y, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(node_id) DO UPDATE SET
                            x=excluded.x, y=excluded.y, updated_at=excluded.updated_at
                        """,
                        [
                            (position.node_id, position.x, position.y, timestamp)
                            for position in source_positions
                        ],
                    )
                    connection.executemany(
                        """
                        UPDATE topology_element SET x=?, y=?, updated_at=?
                        WHERE element_id=?
                        """,
                        [
                            (position.x, position.y, timestamp, position.node_id)
                            for position in element_positions
                        ],
                    )
                if viewport is not None:
                    connection.execute(
                        """
                        INSERT INTO viewport(singleton, x, y, zoom, updated_at)
                        VALUES (1, ?, ?, ?, ?)
                        ON CONFLICT(singleton) DO UPDATE SET
                            x=excluded.x, y=excluded.y, zoom=excluded.zoom,
                            updated_at=excluded.updated_at
                        """,
                        (viewport.x, viewport.y, viewport.zoom, timestamp),
                    )

        await self._run(operation)

    async def load_layout(self) -> LayoutState:
        def operation() -> tuple[
            list[dict[str, Any]],
            dict[str, Any] | None,
            int,
        ]:
            with self._connect() as connection:
                positions = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT node_id, x, y FROM node_layout"
                    ).fetchall()
                ]
                positions.extend(
                    {
                        "node_id": row["element_id"],
                        "x": row["x"],
                        "y": row["y"],
                    }
                    for row in connection.execute(
                        "SELECT element_id, x, y FROM topology_element"
                    ).fetchall()
                )
                viewport_row = connection.execute(
                    "SELECT x, y, zoom FROM viewport WHERE singleton=1"
                ).fetchone()
                metadata_row = connection.execute(
                    "SELECT visual_version FROM layout_metadata WHERE singleton=1"
                ).fetchone()
                return (
                    positions,
                    dict(viewport_row) if viewport_row else None,
                    (
                        int(metadata_row["visual_version"])
                        if metadata_row
                        else CURRENT_LAYOUT_VISUAL_VERSION
                    ),
                )

        rows, viewport_row, visual_version = await self._run(operation)
        positions = {row["node_id"]: Position(x=row["x"], y=row["y"]) for row in rows}
        viewport = Viewport(**viewport_row) if viewport_row else None
        return LayoutState(
            positions=positions,
            viewport=viewport,
            visual_version=visual_version,
        )

    async def reset_layout(
        self,
        visual_version: int = CURRENT_LAYOUT_VISUAL_VERSION,
    ) -> None:
        def operation() -> None:
            with self._connect() as connection:
                connection.execute("DELETE FROM node_layout")
                connection.execute("DELETE FROM viewport")
                connection.execute(
                    """
                    INSERT INTO layout_metadata(singleton, visual_version, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        visual_version=excluded.visual_version,
                        updated_at=excluded.updated_at
                    """,
                    (visual_version, utc_now().isoformat()),
                )

        await self._run(operation)

    async def set_layout_visual_version(self, visual_version: int) -> None:
        if visual_version < 1:
            raise ValueError("visual_version must be positive")

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO layout_metadata(singleton, visual_version, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        visual_version=excluded.visual_version,
                        updated_at=excluded.updated_at
                    """,
                    (visual_version, utc_now().isoformat()),
                )

        await self._run(operation)

    async def prune_layout(
        self,
        active_node_ids: set[str],
        retention_days: int = 180,
    ) -> int:
        now = utc_now()
        cutoff = (now - timedelta(days=retention_days)).isoformat()

        def operation() -> int:
            with self._connect() as connection:
                if not active_node_ids:
                    cursor = connection.execute(
                        "DELETE FROM node_layout WHERE updated_at < ?", (cutoff,)
                    )
                    return cursor.rowcount
                parameters = sorted(active_node_ids)
                connection.executemany(
                    "UPDATE node_layout SET updated_at=? WHERE node_id=?",
                    [(now.isoformat(), node_id) for node_id in parameters],
                )
                stale_rows = connection.execute(
                    "SELECT node_id FROM node_layout WHERE updated_at < ?",
                    (cutoff,),
                ).fetchall()
                stale_ids = [
                    row["node_id"] for row in stale_rows if row["node_id"] not in active_node_ids
                ]
                connection.executemany(
                    "DELETE FROM node_layout WHERE node_id=?",
                    [(node_id,) for node_id in stale_ids],
                )
                return len(stale_ids)

        return await self._run(operation)
