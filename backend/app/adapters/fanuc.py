from app.models.schemas import ConnectionType

from .base import BaseAdapter


class FanucAdapter(BaseAdapter):
    endpoint = "/runtime/focas/fsopenconnection"
    module_name = "focas"
    connection_type = ConnectionType.FANUC_CNC
    label = "Fanuc CNC"
    icon = "/icons/Fanuc.svg"
    subtype = "Fanuc FOCAS"
    container_keys = ("fsopenconnection", "fsopenconnections", *BaseAdapter.container_keys)
    status_fields = ("ConnectionStatus", "connectionStatus")
