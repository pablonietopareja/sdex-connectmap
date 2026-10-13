import type {
  ConnectionStatus,
  ConnectionType,
  ThemePreference,
} from "./types";

export interface ConnectionTypePresentation {
  label: string;
  shortLabel: string;
  icon: string;
  group: "plc" | "cnc" | "field" | "service" | "gateway";
}

export const CONNECTION_PRESENTATION: Record<
  ConnectionType,
  ConnectionTypePresentation
> = {
  sdex_gateway: {
    label: "SDEX Gateway",
    shortLabel: "SDEX",
    icon: "/icons/SDEX.svg",
    group: "gateway",
  },
  siemens_s7_1200_1500: {
    label: "Siemens S7-1200/1500",
    shortLabel: "S7-1200/1500",
    icon: "/icons/S7_2.svg",
    group: "plc",
  },
  siemens_s7_300_400: {
    label: "Siemens S7-300/400",
    shortLabel: "S7-300/400",
    icon: "/icons/S7.svg",
    group: "plc",
  },
  rockwell_allen_bradley: {
    label: "Allen-Bradley / Rockwell",
    shortLabel: "Rockwell",
    icon: "/icons/Rockwell.svg",
    group: "plc",
  },
  modbus: {
    label: "Modbus",
    shortLabel: "Modbus",
    icon: "/icons/Modbus.svg",
    group: "field",
  },
  sinumerik_840d: {
    label: "SINUMERIK 840D",
    shortLabel: "SINUMERIK",
    icon: "/icons/Sinumerik.svg",
    group: "cnc",
  },
  fanuc_cnc: {
    label: "Fanuc CNC",
    shortLabel: "Fanuc",
    icon: "/icons/Fanuc.svg",
    group: "cnc",
  },
  opcua_remote_server: {
    label: "OPC UA Server",
    shortLabel: "OPC UA Servers",
    icon: "/icons/OPC_UA_Server.svg",
    group: "service",
  },
  opcua_local_endpoint: {
    label: "OPC UA Endpoint",
    shortLabel: "OPC UA Endpoints",
    icon: "/icons/OPC_UA_Server.svg",
    group: "service",
  },
  mqtt_broker: {
    label: "MQTT Broker",
    shortLabel: "MQTT",
    icon: "/icons/MQTT.svg",
    group: "service",
  },
};

export const STATUS_LABELS: Record<ConnectionStatus, string> = {
  connected: "Connected",
  disconnected: "Disconnected",
  disabled: "Disabled",
  unlicensed: "Unlicensed",
  degraded: "Degraded",
  unknown: "Unknown",
};

export const REFRESH_OPTIONS = [
  { value: 60, label: "1 minute" },
  { value: 300, label: "5 minutes" },
  { value: 600, label: "10 minutes" },
  { value: 900, label: "15 minutes" },
  { value: 1800, label: "30 minutes" },
  { value: 3600, label: "1 hour" },
] as const;

export const THEMES: readonly ThemePreference[] = [
  "light",
  "dark",
  "system",
];

export const DEFAULT_VIEWPORT = { x: 0, y: 0, zoom: 1 };
export const GATEWAY_ID = "sdex_gateway:sdex";
