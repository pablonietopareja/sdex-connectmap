import type {
  ConnectionNode,
  ConnectionStatus,
  Point,
  SdexInterfaceName,
} from "./topology";

export type VisualElementType = "rack" | "switch";
export type RoutingMode = "auto" | "manual" | "orthogonal";
export type WaypointKind = "free" | "corner";

export interface EdgeWaypoint {
  id: string;
  x: number;
  y: number;
  kind: WaypointKind;
  order: number;
}

export interface EdgeRoute {
  edge_id: string;
  routing_mode: RoutingMode;
  waypoints: EdgeWaypoint[];
  schema_version: number;
  updated_at: string;
}

export interface AggregateStatus {
  status: ConnectionStatus;
  total: number;
  connected: number;
  disconnected: number;
  disabled: number;
  unknown: number;
  degraded: number;
  missing: number;
  animated: boolean;
}

interface VisualElementBase {
  id: string;
  type: VisualElementType;
  name: string;
  description: string | null;
  position: Point;
  width: number;
  height: number;
  external_interface: SdexInterfaceName | null;
  derived_external_interface?: SdexInterfaceName | null;
  effective_external_interface?: SdexInterfaceName | null;
  interface_conflict?: boolean;
  schema_version: number;
  created_at: string;
  updated_at: string;
}

export interface RackElement extends VisualElementBase {
  type: "rack";
  rows: number;
  columns: number;
  capacity: number;
  collapsed: boolean;
  aggregate: AggregateStatus;
}

export interface VisualSwitch extends VisualElementBase {
  type: "switch";
  icon: "/icons/Switch.svg";
  status_mode: "neutral" | "aggregate";
  aggregate?: AggregateStatus | null;
}

export type VisualElement = RackElement | VisualSwitch;

export interface RackMembership {
  rack_id: string;
  connection_id: string;
  row: number;
  column: number;
  missing: boolean;
  connection: ConnectionNode | null;
  unresolved_interface_confirmed?: boolean;
  cached_display_name?: string | null;
  cached_connection_type?: string | null;
  cached_subtype?: string | null;
  cached_icon?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface VisualLink {
  id: string;
  source: string;
  target: string;
  source_handle: string | null;
  target_handle: string | null;
  external_interface: SdexInterfaceName | null;
  unresolved_interface_confirmed?: boolean;
  schema_version: number;
  created_at: string;
  updated_at: string;
}

export interface VisualTopology {
  elements: VisualElement[];
  rack_memberships: RackMembership[];
  links: VisualLink[];
  routes: Record<string, EdgeRoute>;
  unrouted_connection_ids: string[];
}

export interface VisualElementCreate {
  /** Used by Undo/Redo to restore a deleted local visual element. */
  id?: string;
  type: VisualElementType;
  position: Point;
  name?: string;
  description?: string | null;
  rows?: number;
  columns?: number;
  external_interface?: SdexInterfaceName | null;
  status_mode?: "neutral" | "aggregate";
}

export interface VisualElementUpdate {
  name?: string;
  description?: string | null;
  position?: Point;
  rows?: number;
  columns?: number;
  collapsed?: boolean;
  external_interface?: SdexInterfaceName | null;
  status_mode?: "neutral" | "aggregate";
  overflow_policy?: "reject" | "eject";
}

export interface RackMembershipUpdate {
  connection_id: string;
  row: number;
  column: number;
  allow_unresolved_interface?: boolean;
}

export interface VisualLinkCreate {
  /** Used by Undo/Redo to restore a deleted local visual link. */
  id?: string;
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
  external_interface?: SdexInterfaceName | null;
  allow_unresolved_interface?: boolean;
}

export interface VisualLinkUpdate {
  target?: string;
  source_handle?: string | null;
  target_handle?: string | null;
  external_interface?: SdexInterfaceName | null;
  allow_unresolved_interface?: boolean;
}

export interface EdgeRouteUpdate {
  routing_mode: RoutingMode;
  waypoints: EdgeWaypoint[];
}

export const EMPTY_VISUAL_TOPOLOGY: VisualTopology = {
  elements: [],
  rack_memberships: [],
  links: [],
  routes: {},
  unrouted_connection_ids: [],
};
