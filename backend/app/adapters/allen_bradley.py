from app.models.schemas import ConnectionType

from .base import BaseAdapter


class AllenBradleyAdapter(BaseAdapter):
    endpoint = "/runtime/allenbradley/connections"
    module_name = "allenbradley"
    connection_type = ConnectionType.ROCKWELL_ALLEN_BRADLEY
    label = "Rockwell / Allen-Bradley"
    icon = "/icons/Rockwell.svg"
    subtype = "Allen-Bradley"
    container_keys = ("allenbradleyConns", "allenBradleyConnections", *BaseAdapter.container_keys)
    status_fields = ("ConnectionStatus", "connectionStatus")
