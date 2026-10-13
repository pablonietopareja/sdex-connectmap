from __future__ import annotations

import asyncio
import copy
from typing import Any

from .sdex_client import (
    NETWORK_INTERFACES_PATH,
    ModuleUnavailableError,
    TransientModuleError,
)

SYSTEM_FIXTURE: dict[str, Any] = {
    "productType": "SDEX Suite (Mock)",
    "version": "3.01-mock",
    "status": "Running",
    "fqdn": "sdex-mock.local",
    "hostname": "sdex-mock",
    "httpAPI": "3.01",
    "OS": "Linux",
    "arch": "arm64",
    "demo": True,
    "allConnected": False,
}

VISUAL_PREVIEW_SYSTEM_FIXTURE: dict[str, Any] = {
    "productType": "SDEX Suite",
    "version": "1.0-preview",
    "status": "Running",
    "fqdn": "sdex-edgenode.local",
    "hostname": "sdex-edgenode",
    "httpAPI": "1.0",
    "OS": "Linux",
    "arch": "amd64",
    "demo": False,
    "allConnected": True,
}

NETWORK_INTERFACES_FIXTURE: dict[str, Any] = {
    "fqdn": "sdex-mock.local",
    "hostname": "sdex-mock",
    "ipv4": [
        {"eth1": "10.20.0.1/24"},
    ],
    "ipv6": [
        {"eth2": "fd00::1/64"},
    ],
}

VISUAL_PREVIEW_NETWORK_INTERFACES_FIXTURE: dict[str, Any] = {
    "fqdn": "sdex-edgenode.local",
    "hostname": "sdex-edgenode",
    "ipv4": [
        {"eth1": "192.168.10.1/24"},
        {"eth2": "192.168.20.1/24"},
    ],
    "ipv6": [],
}


BASE_FIXTURES: dict[str, Any] = {
    NETWORK_INTERFACES_PATH: NETWORK_INTERFACES_FIXTURE,
    "/runtime/siemenss72/s72connection": [
        {
            "Name": "Packaging S7-1500",
            "Address": "10.20.0.11",
            "Port": 102,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": True,
            "Rack": 0,
            "Slot": 1,
        }
    ],
    "/runtime/siemenss32/s32connection": [
        {
            "Name": "Legacy S7-300",
            "Address": "10.20.0.12",
            "Port": 102,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": False,
            "Rack": 0,
            "Slot": 2,
        }
    ],
    "/runtime/allenbradley/connections": [
        {
            "Name": "ControlLogix",
            "Address": "10.20.0.21",
            "Port": 44818,
            "Enabled": True,
        }
    ],
    "/runtime/modbus/modbusconnection": [
        {
            "Name": "Energy Meter",
            "Address": "10.20.0.31",
            "Port": 502,
            "Enabled": False,
            "Licensed": True,
            "ConnectionStatus": False,
            "Unitid": 1,
        }
    ],
    "/runtime/siemens840d/s840dconnection": [
        {
            "Name": "SINUMERIK Cell",
            "Address": "10.20.0.41",
            "Port": 102,
            "Enabled": True,
            "Licensed": True,
            "EnableNCK": True,
            "EnablePLC": True,
            "ConnectionStatus": True,
            "ConnectionStatus-PLC": False,
        }
    ],
    "/runtime/focas/fsopenconnection": [
        {
            "Name": "Fanuc Mill",
            "Address": "10.20.0.51",
            "Port": 8193,
            "Enabled": True,
            "Licensed": False,
        }
    ],
    "/runtime/opcua-client/connections": {
        "connections": [
            {
                "name": "Historian OPC UA",
                "URL": "opc.tcp://[fd00::20]:4840",
                "Enabled": True,
                "Licensed": True,
                "ConnectionStatus": "CONNECTED",
                "securityMode": "SignAndEncrypt",
            }
        ]
    },
    "/runtime/opcua-server/endpoints": [
        {
            "name": "SDEX Local Endpoint",
            "endpoint-url": "opc.tcp://localhost:4840",
            "enabled": True,
            "accessProtection": {"endpointStatus": False},
        }
    ],
    "/runtime/mqtt/connections": [
        {
            "connectionName": "Plant Broker",
            "hostname": "mqtt.internal",
            "port": 8883,
            "enabled": True,
            "licensed": True,
            "connectionState": "Connected",
            "proxySettings": {"password": "fixture-must-never-leak"},
        }
    ],
}

VISUAL_PREVIEW_FIXTURES: dict[str, Any] = {
    NETWORK_INTERFACES_PATH: VISUAL_PREVIEW_NETWORK_INTERFACES_FIXTURE,
    "/runtime/siemenss72/s72connection": [
        {
            "Name": "Packaging PLC",
            "Model": "Siemens S7-1500",
            "Address": "192.168.10.11",
            "Port": 102,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": True,
            "Rack": 0,
            "Slot": 1,
        }
    ],
    "/runtime/siemenss32/s32connection": [
        {
            "Name": "Legacy Line PLC",
            "Model": "Siemens S7-400",
            "Address": "192.168.10.12",
            "Port": 102,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": True,
            "Rack": 0,
            "Slot": 2,
        }
    ],
    "/runtime/allenbradley/connections": [
        {
            "Name": "Assembly ControlLogix",
            "Model": "ControlLogix",
            "Address": "192.168.10.13",
            "Port": 44818,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": True,
        }
    ],
    "/runtime/modbus/modbusconnection": [
        {
            "Name": "Energy Meter",
            "Model": "Modbus TCP",
            "Address": "192.168.10.14",
            "Port": 502,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": True,
            "Unitid": 1,
        }
    ],
    "/runtime/siemens840d/s840dconnection": [
        {
            "Name": "CNC Milling Center",
            "Model": "SINUMERIK 840D",
            "Address": "192.168.20.15",
            "Port": 102,
            "Enabled": True,
            "Licensed": True,
            "EnableNCK": True,
            "EnablePLC": True,
            "ConnectionStatus": True,
            "ConnectionStatus-PLC": True,
        }
    ],
    "/runtime/focas/fsopenconnection": [
        {
            "Name": "Fanuc Machining Cell",
            "Model": "FANUC 30i",
            "Address": "192.168.20.16",
            "Port": 8193,
            "Enabled": True,
            "Licensed": True,
            "ConnectionStatus": True,
        }
    ],
    "/runtime/opcua-client/connections": {
        "connections": [
            {
                "name": "Production OPC UA Server",
                "Model": "Remote OPC UA Server",
                "URL": "opc.tcp://192.168.20.17:4840",
                "Enabled": True,
                "Licensed": True,
                "ConnectionStatus": "Connected",
                "securityMode": "None",
            }
        ]
    },
    # The visual preview represents the remote server consumed by SDEX, not
    # an OPC UA endpoint published locally by SDEX.
    "/runtime/opcua-server/endpoints": [],
    "/runtime/mqtt/connections": [
        {
            "connectionName": "Factory MQTT Broker",
            "Model": "MQTT 3.1.1 Broker",
            "hostname": "192.168.20.18",
            "port": 1883,
            "enabled": True,
            "licensed": True,
            "connectionState": "connected",
            "TLS": False,
        }
    ],
}


class MockSDEXClient:
    """In-process development source. It is never selected unless mock mode is explicit."""

    def __init__(self, scenario: str = "dynamic") -> None:
        self.scenario = scenario
        self._cycle = 0
        self._lock = asyncio.Lock()

    async def login(self) -> None:
        return None

    async def get_system(self) -> dict[str, Any]:
        if self.scenario == "offline":
            raise TransientModuleError("Mock SDEX gateway is offline.")
        async with self._lock:
            self._cycle += 1
        fixture = (
            VISUAL_PREVIEW_SYSTEM_FIXTURE
            if self.scenario in {"visual_preview", "editor_preview"}
            else SYSTEM_FIXTURE
        )
        return copy.deepcopy(fixture)

    async def get_json(self, path: str) -> Any:
        if self.scenario == "partial" and path == "/runtime/mqtt/connections":
            raise TransientModuleError("Injected MQTT module failure.")
        if self.scenario == "missing_modules" and path in {
            "/runtime/focas/fsopenconnection",
            "/runtime/siemens840d/s840dconnection",
        }:
            raise ModuleUnavailableError("Injected unavailable module.")
        fixtures = (
            VISUAL_PREVIEW_FIXTURES
            if self.scenario in {"visual_preview", "editor_preview"}
            else BASE_FIXTURES
        )
        if path not in fixtures:
            raise ModuleUnavailableError("Mock endpoint is unavailable.")
        payload = copy.deepcopy(fixtures[path])
        if self.scenario == "dynamic":
            if path == "/runtime/mqtt/connections" and self._cycle % 2 == 0:
                payload[0]["connectionState"] = "DISCONNECTED"
            if path == "/runtime/siemenss72/s72connection" and self._cycle % 3 == 0:
                payload.append(
                    {
                        "Name": "Temporary Skid",
                        "Address": "10.20.0.61",
                        "Port": 102,
                        "Enabled": True,
                        "Licensed": True,
                        "ConnectionStatus": True,
                    }
                )
        return payload

    async def close(self) -> None:
        return None
