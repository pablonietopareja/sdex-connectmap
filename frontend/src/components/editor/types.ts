import type {
  ConnectionStatus,
  Point,
  SdexInterfaceName,
} from "../../types";

export type VisualTool = "rack" | "switch";

export interface RackSlotView {
  row: number;
  column: number;
  connection_id: string | null;
}

export interface RackElementView {
  id: string;
  type: "rack";
  name: string;
  rows: number;
  columns: number;
  capacity: number;
  position?: Point;
  width?: number;
  height?: number;
  member_ids: string[];
  slot_assignments: RackSlotView[];
  collapsed?: boolean;
  external_interface: SdexInterfaceName | null;
  derived_external_interface?: SdexInterfaceName | null;
  effective_external_interface?: SdexInterfaceName | null;
  interface_conflict?: boolean;
  schema_version?: number;
  created_at?: string;
  updated_at?: string;
  aggregate?: RackAggregateCounts & {
    status: ConnectionStatus;
    degraded?: number;
    missing?: number;
    animated?: boolean;
  };
}

export interface RackAggregateCounts {
  total: number;
  connected: number;
  disconnected: number;
  unknown: number;
  disabled: number;
}

export interface RackNodeViewData extends Record<string, unknown> {
  rack: RackElementView;
  editorEnabled: boolean;
  aggregateStatus: ConnectionStatus;
  aggregateCounts: RackAggregateCounts;
  missingMemberIds?: readonly string[];
  highlightedSlot?: Pick<RackSlotView, "row" | "column"> | null;
  onOpen: (rack: RackElementView) => void;
}

export interface SwitchElementView {
  id: string;
  type: "switch";
  name: string;
  description?: string | null;
  position?: Point;
  icon?: string;
  external_interface: SdexInterfaceName | null;
  derived_external_interface?: SdexInterfaceName | null;
  effective_external_interface?: SdexInterfaceName | null;
  interface_conflict?: boolean;
  status_mode?: "neutral" | "aggregate";
  aggregate?: RackElementView["aggregate"] | null;
  schema_version?: number;
  created_at?: string;
  updated_at?: string;
}

export interface SwitchHandleView {
  id: string;
  side: "left" | "right";
  type: "source" | "target";
  label?: string;
}

export interface SwitchNodeViewData extends Record<string, unknown> {
  visualSwitch: SwitchElementView;
  editorEnabled: boolean;
  handles: readonly SwitchHandleView[];
  onOpen: (visualSwitch: SwitchElementView) => void;
}

export interface RackPropertiesUpdate {
  name: string;
  rows: number;
  columns: number;
  external_interface: SdexInterfaceName | null;
}

export interface SwitchPropertiesUpdate {
  name: string;
  description: string | null;
  external_interface: SdexInterfaceName | null;
}
