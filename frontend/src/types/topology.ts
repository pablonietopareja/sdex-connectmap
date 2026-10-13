export const CONNECTION_TYPES = [
  "sdex_gateway",
  "siemens_s7_1200_1500",
  "siemens_s7_300_400",
  "rockwell_allen_bradley",
  "modbus",
  "sinumerik_840d",
  "fanuc_cnc",
  "opcua_remote_server",
  "opcua_local_endpoint",
  "mqtt_broker",
] as const;

export type ConnectionType = (typeof CONNECTION_TYPES)[number];

export const CONNECTION_STATUSES = [
  "connected",
  "disconnected",
  "disabled",
  "unlicensed",
  "degraded",
  "unknown",
] as const;

export type ConnectionStatus = (typeof CONNECTION_STATUSES)[number];

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  | JsonPrimitive
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface Subchannel {
  name: string;
  enabled?: boolean;
  status: ConnectionStatus;
  reason?: string;
}

export type SdexInterfaceName = "eth1" | "eth2";

export type NetworkInterfaceSource =
  | "sdex"
  | "manual"
  | "sdex_with_manual_prefix"
  | "mock";

export interface NetworkAddress {
  address: string;
  prefix_length: number | null;
  network: string | null;
  version: 4 | 6;
}

export interface NetworkInterface {
  name: string;
  addresses: NetworkAddress[];
  source: NetworkInterfaceSource;
}

export type InterfaceAssignmentSource =
  | "explicit"
  | "manual_override"
  | "subnet"
  | "gateway_local"
  | "unresolved";

export interface InterfaceAssignment {
  resolved: boolean;
  interface_name: string | null;
  source: InterfaceAssignmentSource;
  reason: string;
  /** External edge interfaces considered by ConnectMap; Docker-internal eth0/lo are excluded. */
  candidate_interfaces?: SdexInterfaceName[];
}

export type ConnectionSourceHandle = "top" | "right" | "bottom" | "left";

export interface DeviceVisualRouting {
  connection_id: string;
  preferred_source_handle: ConnectionSourceHandle;
  updated_at: string;
}

export interface EdgeVisualStyle {
  edge_id: string;
  sheath_color: string;
  flow_color: string;
  /**
   * Older persisted snapshots may not contain this field. Missing values are
   * interpreted as the default device-to-SDEX direction.
   */
  reverse_flow?: boolean;
  updated_at: string;
  schema_version: number;
}

export interface EdgeVisualStyleUpdate {
  sheath_color: string;
  flow_color: string;
  reverse_flow: boolean;
}

export interface ConnectionNode {
  id: string;
  type: ConnectionType;
  subtype?: string | null;
  display_name: string;
  address?: string | null;
  host?: string | null;
  port?: number | null;
  endpoint_url?: string | null;
  enabled: boolean;
  licensed?: boolean | null;
  status: ConnectionStatus;
  status_reason?: string | null;
  source_module: string;
  icon: string;
  metadata: Record<string, JsonValue>;
  last_seen_at?: string | null;
  last_status_change_at?: string | null;
  stale: boolean;
  capabilities?: Record<string, JsonValue> | null;
  subchannels?: Subchannel[] | null;
  interface_assignment?: InterfaceAssignment | null;
  /** True when this entry describes a service hosted by the SDEX gateway itself. */
  local_service?: boolean;
  /** Whether a gateway-local service is tied to one external edge interface. */
  interface_scope?: "gateway-local" | "single-external" | null;
  /** Session state is kept separate from endpoint availability. */
  session_telemetry?:
    | "unavailable"
    | "unknown"
    | "connected"
    | "disconnected"
    | null;
  /**
   * Compatibility fields for snapshots produced before InterfaceAssignment was
   * introduced. New snapshots should use interface_assignment.
   */
  network_interface?: string | null;
  network_interface_source?: string | null;
  network_interface_reason?: string | null;
}

export type ModuleDiscoveryStatus =
  | "ok"
  | "unavailable"
  | "forbidden"
  | "authentication_error"
  | "default_password"
  | "temporary_error"
  | "parse_error";

export interface ModuleResult {
  module: string;
  status: ModuleDiscoveryStatus;
  count: number;
  error?: string | null;
}

export interface TopologySummary {
  total_configured: number;
  enabled: number;
  connected: number;
  disconnected: number;
  disabled: number;
  unknown_degraded: number;
  by_type: Partial<Record<ConnectionType, number>>;
}

export interface Point {
  x: number;
  y: number;
}

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface LayoutState {
  positions: Record<string, Point>;
  viewport: Viewport | null;
  visual_version?: number;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  source_handle: string | null;
  target_handle: string | null;
  interface_assignment: InterfaceAssignment;
  style: EdgeVisualStyle | null;
  kind?: "source" | "visual" | "aggregate";
  route?: import("./visual-topology").EdgeRoute | null;
  aggregate?: import("./visual-topology").AggregateStatus | null;
}

export interface TopologySnapshot {
  gateway: ConnectionNode;
  nodes: ConnectionNode[];
  network_interfaces?: NetworkInterface[];
  edges?: TopologyEdge[];
  /**
   * Transitional compatibility for snapshots that exposed styles separately.
   * Canonical snapshots embed style in each TopologyEdge.
   */
  edge_styles?: Record<string, EdgeVisualStyle>;
  module_results: ModuleResult[];
  summary: TopologySummary;
  generated_at?: string | null;
  last_successful_refresh?: string | null;
  stale: boolean;
  partial: boolean;
  refresh_in_progress: boolean;
  last_error?: string | null;
  mock_mode: boolean;
  layout: LayoutState;
  visual_topology?: import("./visual-topology").VisualTopology;
  alarms?: import("./alarms").TopologyAlarm[];
}

export interface LayoutUpdate {
  positions?: Array<{ node_id: string; x: number; y: number }>;
  viewport?: Viewport;
}
