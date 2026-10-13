import { calculateSummary } from "../utils";
import type {
  ConnectionNode,
  ConnectionType,
  TopologySnapshot,
} from "../types";

export function makeNode(
  overrides: Partial<ConnectionNode> = {},
): ConnectionNode {
  return {
    id: "modbus:line-1",
    type: "modbus",
    subtype: null,
    display_name: "Packaging PLC",
    address: "10.20.0.41",
    host: "10.20.0.41",
    port: 502,
    endpoint_url: null,
    enabled: true,
    licensed: true,
    status: "connected",
    status_reason: "ConnectionStatus reported true",
    source_module: "modbus",
    icon: "Modbus.svg",
    metadata: { rack: 0 },
    last_seen_at: "2026-07-28T08:30:00Z",
    last_status_change_at: "2026-07-28T07:30:00Z",
    stale: false,
    capabilities: null,
    interface_assignment: {
      resolved: true,
      interface_name: "eth1",
      source: "subnet",
      reason: "Address belongs to the eth1 test subnet.",
    },
    ...overrides,
  };
}

export function makeGateway(
  overrides: Partial<ConnectionNode> = {},
): ConnectionNode {
  return makeNode({
    id: "sdex_gateway:sdex",
    type: "sdex_gateway",
    display_name: "SDEX Suite",
    address: "sdex-suite",
    host: "sdex-suite",
    port: 443,
    source_module: "core",
    icon: "SDEX.svg",
    metadata: {
      product_type: "SDEX Suite",
      fqdn: "sdex-suite.edge.local",
      os: "Linux",
      arch: "arm64",
    },
    ...overrides,
  });
}

export function makeSnapshot(
  nodes: ConnectionNode[] = [
    makeNode(),
    makeNode({
      id: "mqtt:edge-broker",
      type: "mqtt_broker",
      display_name: "Edge broker",
      host: "mqtt.internal",
      address: "mqtt.internal",
      port: 8883,
      icon: "MQTT.svg",
    }),
  ],
  overrides: Partial<TopologySnapshot> = {},
): TopologySnapshot {
  return {
    gateway: makeGateway(),
    nodes,
    module_results: [
      { module: "modbus", status: "ok", count: 1 },
      { module: "mqtt", status: "ok", count: 1 },
    ],
    summary: calculateSummary(nodes),
    generated_at: "2026-07-28T08:30:00Z",
    last_successful_refresh: "2026-07-28T08:30:00Z",
    stale: false,
    partial: false,
    refresh_in_progress: false,
    last_error: null,
    mock_mode: false,
    layout: { positions: {}, viewport: null },
    ...overrides,
  };
}

export const DEVICE_TYPES: ConnectionType[] = [
  "siemens_s7_1200_1500",
  "siemens_s7_300_400",
  "rockwell_allen_bradley",
  "modbus",
  "sinumerik_840d",
  "fanuc_cnc",
  "opcua_remote_server",
  "opcua_local_endpoint",
  "mqtt_broker",
];
