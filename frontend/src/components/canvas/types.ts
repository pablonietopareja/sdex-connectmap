import type { Edge, Node } from "@xyflow/react";
import type {
  AggregateStatus,
  ConnectionNode,
  ConnectionStatus,
  EdgeRoute,
  EdgeRouteUpdate,
  EdgeVisualStyle,
  NetworkInterface,
  SdexInterfaceName,
} from "../../types";
import type { RackFlowNode } from "../nodes/RackNodeCard";
import type { SwitchFlowNode } from "../nodes/SwitchNodeCard";

export interface ConnectionNodeData extends Record<string, unknown> {
  connection: ConnectionNode;
  editorEnabled: boolean;
  variant?: "standalone" | "embedded";
  rackId?: string;
  onOpen: (node: ConnectionNode) => void;
}

export interface GatewayNodeData extends Record<string, unknown> {
  connection: ConnectionNode;
  onOpen: (node: ConnectionNode) => void;
  networkInterfaces?: NetworkInterface[];
}

export interface DataCableEdgeData extends Record<string, unknown> {
  status: ConnectionStatus;
  reason?: string | null;
  stale: boolean;
  style: EdgeVisualStyle | null;
  connectionName: string;
  networkInterface: SdexInterfaceName;
  onConfigure: (edgeId: string) => void;
  route?: EdgeRoute | null;
  editorEnabled?: boolean;
  aggregate?: AggregateStatus | null;
  flowAnimated?: boolean;
  onSaveRoute?: (
    edgeId: string,
    update: EdgeRouteUpdate,
  ) => Promise<EdgeRoute | void>;
  onResetRoute?: (edgeId: string) => Promise<void>;
}

export type ConnectionFlowNode = Node<ConnectionNodeData, "connection">;
export type GatewayFlowNode = Node<GatewayNodeData, "gateway">;
export type ConnectMapFlowNode =
  | ConnectionFlowNode
  | GatewayFlowNode
  | RackFlowNode
  | SwitchFlowNode;
export type DataCableFlowEdge = Edge<DataCableEdgeData, "dataCable">;
