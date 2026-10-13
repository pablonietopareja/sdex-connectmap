from collections.abc import Mapping
from typing import Any

from app.models.schemas import ConnectionStatus, ConnectionType

from .base import BaseAdapter, get_field, normalize_status_value


class MqttAdapter(BaseAdapter):
    endpoint = "/runtime/mqtt/connections"
    module_name = "mqtt"
    connection_type = ConnectionType.MQTT_BROKER
    label = "MQTT Broker"
    icon = "/icons/MQTT.svg"
    subtype = "MQTT Broker"
    address_fields = ("hostname", "host", *BaseAdapter.address_fields)
    status_fields = ("connectionState", "ConnectionState", *BaseAdapter.status_fields)

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
        state = get_field(record, "connectionState", "ConnectionState")
        status = normalize_status_value(state if state is not None else raw_status)
        if status == ConnectionStatus.CONNECTED:
            return status, "SDEX reports that the MQTT broker connection is connected."
        if status == ConnectionStatus.DISCONNECTED:
            return status, "SDEX reports that the MQTT broker connection is disconnected."
        if status == ConnectionStatus.DEGRADED:
            return status, "SDEX reports an MQTT broker error state."
        return status, "The MQTT connection state is unavailable or unrecognized."
