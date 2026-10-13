from app.models.schemas import ConnectionType

from .base import BaseAdapter


class SiemensS772Adapter(BaseAdapter):
    endpoint = "/runtime/siemenss72/s72connection"
    module_name = "siemenss72"
    connection_type = ConnectionType.SIEMENS_S7_1200_1500
    label = "S7-1200/1500"
    icon = "/icons/S7_2.svg"
    subtype = "Siemens S7-1200/1500"
    container_keys = ("s72connection", "s72connections", *BaseAdapter.container_keys)
