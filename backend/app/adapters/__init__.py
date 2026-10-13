from .allen_bradley import AllenBradleyAdapter
from .base import BaseAdapter
from .fanuc import FanucAdapter
from .modbus import ModbusAdapter
from .mqtt import MqttAdapter
from .opcua import OpcUaClientAdapter, OpcUaServerAdapter
from .siemens_s7_32 import SiemensS732Adapter
from .siemens_s7_72 import SiemensS772Adapter
from .sinumerik import SinumerikAdapter


def default_adapters() -> list[BaseAdapter]:
    return [
        SiemensS772Adapter(),
        SiemensS732Adapter(),
        AllenBradleyAdapter(),
        ModbusAdapter(),
        SinumerikAdapter(),
        FanucAdapter(),
        OpcUaClientAdapter(),
        OpcUaServerAdapter(),
        MqttAdapter(),
    ]


__all__ = [
    "AllenBradleyAdapter",
    "BaseAdapter",
    "FanucAdapter",
    "ModbusAdapter",
    "MqttAdapter",
    "OpcUaClientAdapter",
    "OpcUaServerAdapter",
    "SiemensS732Adapter",
    "SiemensS772Adapter",
    "SinumerikAdapter",
    "default_adapters",
]
