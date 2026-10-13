from app.models.schemas import ConnectionType

from .base import BaseAdapter


class ModbusAdapter(BaseAdapter):
    endpoint = "/runtime/modbus/modbusconnection"
    module_name = "modbus"
    connection_type = ConnectionType.MODBUS
    label = "Modbus"
    icon = "/icons/Modbus.svg"
    subtype = "Modbus TCP"
    container_keys = ("modbusconnection", "modbusconnections", *BaseAdapter.container_keys)
