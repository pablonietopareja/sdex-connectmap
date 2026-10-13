from app.models.schemas import ConnectionType

from .base import BaseAdapter


class SiemensS732Adapter(BaseAdapter):
    endpoint = "/runtime/siemenss32/s32connection"
    module_name = "siemenss32"
    connection_type = ConnectionType.SIEMENS_S7_300_400
    label = "S7-300/400"
    icon = "/icons/S7.svg"
    subtype = "Siemens S7-300/400"
    container_keys = ("s32connection", "s32connections", *BaseAdapter.container_keys)
