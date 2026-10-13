from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.models.schemas import ConnectionStatus, ConnectionType

from .base import BaseAdapter, get_field, normalize_status_value, parse_bool


class SinumerikAdapter(BaseAdapter):
    endpoint = "/runtime/siemens840d/s840dconnection"
    module_name = "siemens840d"
    connection_type = ConnectionType.SINUMERIK_840D
    label = "SINUMERIK 840D"
    icon = "/icons/Sinumerik.svg"
    subtype = "Siemens SINUMERIK 840D"
    container_keys = ("s840dconnection", "s840dconnections", *BaseAdapter.container_keys)

    @staticmethod
    def _subchannel(record: Mapping[str, Any], channel: str) -> dict[str, Any]:
        nested = get_field(record, channel)
        nested_map = nested if isinstance(nested, Mapping) else {}
        prefix = channel.upper()
        enabled = parse_bool(
            get_field(
                record,
                f"{prefix}Enabled",
                f"{channel}Enabled",
                f"Enable{prefix}",
                f"Enabled-{prefix}",
                f"enable{prefix}",
                default=get_field(nested_map, "enabled", "Enabled"),
            )
        )
        status_names = (
            (
                "ConnectionStatus",
                "NCKConnectionStatus",
                "ConnectionStatus-NCK",
                "NCKStatus",
            )
            if channel == "nck"
            else (
                "ConnectionStatus-PLC",
                "PLCConnectionStatus",
                "PLCStatus",
            )
        )
        raw_status = get_field(
            record,
            *status_names,
            default=get_field(nested_map, "connectionStatus", "status", "Status"),
        )
        status = normalize_status_value(raw_status)
        return {
            "enabled": enabled,
            "status": status.value,
        }

    def capabilities(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "subchannels": {
                "nck": self._subchannel(record, "nck"),
                "plc": self._subchannel(record, "plc"),
            }
        }

    def determine_status(
        self,
        record: Mapping[str, Any],
        *,
        enabled: bool,
        licensed: bool | None,
        raw_status: Any,
    ) -> tuple[ConnectionStatus, str]:
        if not enabled or licensed is False:
            return super().determine_status(
                record,
                enabled=enabled,
                licensed=licensed,
                raw_status=raw_status,
            )
        channels = [self._subchannel(record, name) for name in ("nck", "plc")]
        enabled_statuses = [
            ConnectionStatus(channel["status"])
            for channel in channels
            if channel["enabled"] is True
        ]
        if not enabled_statuses:
            if any(channel["enabled"] is not None for channel in channels):
                return (
                    ConnectionStatus.UNKNOWN,
                    "No SINUMERIK NCK or PLC subchannel is currently enabled.",
                )
            return super().determine_status(
                record,
                enabled=enabled,
                licensed=licensed,
                raw_status=raw_status,
            )
        if all(status == ConnectionStatus.CONNECTED for status in enabled_statuses):
            return ConnectionStatus.CONNECTED, "All enabled SINUMERIK subchannels are connected."
        if all(status == ConnectionStatus.DISCONNECTED for status in enabled_statuses):
            return (
                ConnectionStatus.DISCONNECTED,
                "All enabled SINUMERIK subchannels are disconnected.",
            )
        if all(status == ConnectionStatus.UNKNOWN for status in enabled_statuses):
            return (
                ConnectionStatus.UNKNOWN,
                "Enabled SINUMERIK subchannel status is unavailable.",
            )
        return (
            ConnectionStatus.DEGRADED,
            "Enabled SINUMERIK NCK and PLC subchannels report mixed states.",
        )
