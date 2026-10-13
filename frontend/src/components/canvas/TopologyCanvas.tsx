import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
  type Connection,
  type EdgeTypes,
  type NodeTypes,
  type OnMoveEnd,
} from "@xyflow/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  createRadialPositions,
  positionLayoutUpdate,
  withCompleteLayout,
} from "../../utils";
import type {
  ConnectionNode,
  ConnectionSourceHandle,
  EdgeRoute,
  EdgeRouteUpdate,
  EdgeVisualStyle,
  InterfaceAssignment,
  LayoutUpdate,
  Point,
  RackElement,
  RackMembership,
  SdexInterfaceName,
  TopologyEdge,
  TopologySnapshot,
  Viewport,
  VisualElement,
  VisualElementCreate,
  VisualLinkCreate,
  VisualSwitch,
} from "../../types";
import {
  EditorToolbar,
  readVisualToolDrag,
} from "../editor/EditorToolbar";
import type {
  RackElementView,
  RackSlotView,
  SwitchHandleView,
  VisualTool,
} from "../editor/types";
import { Modal } from "../Modal";
import { Notice } from "../Notice";
import { DataCableEdge } from "../edges/DataCableEdge";
import { ConnectionNodeCard } from "../nodes/ConnectionNodeCard";
import { GatewayNodeCard } from "../nodes/GatewayNodeCard";
import {
  EMBEDDED_CONNECTION_HEIGHT,
  EMBEDDED_CONNECTION_WIDTH,
  RACK_CONTENT_PADDING_TOP,
  RACK_HEADER_HEIGHT,
  RACK_PADDING_X,
  RACK_SLOT_GAP,
  RackNodeCard,
  rackDimensions,
  rackSlotPosition,
} from "../nodes/RackNodeCard";
import { SwitchNodeCard } from "../nodes/SwitchNodeCard";
import { CanvasControls } from "./CanvasControls";
import type { ConnectMapFlowNode, DataCableFlowEdge } from "./types";

const NODE_TYPES = {
  connection: ConnectionNodeCard,
  gateway: GatewayNodeCard,
  rack: RackNodeCard,
  switch: SwitchNodeCard,
} as NodeTypes;

const EDGE_TYPES = { dataCable: DataCableEdge } as EdgeTypes;

export function edgeIdForConnection(connectionId: string): string {
  return `sdex-to-${connectionId}`;
}

const CONNECTION_SOURCE_HANDLES = new Set<ConnectionSourceHandle>([
  "top",
  "right",
  "bottom",
  "left",
]);

function asConnectionSourceHandle(
  value: string | null | undefined,
): ConnectionSourceHandle | null {
  return value && CONNECTION_SOURCE_HANDLES.has(value as ConnectionSourceHandle)
    ? (value as ConnectionSourceHandle)
    : null;
}

export function directConnectionReanchor(
  connection: Pick<Connection, "source" | "target" | "sourceHandle" | "targetHandle">,
  snapshot: Pick<TopologySnapshot, "gateway" | "nodes">,
): { connectionId: string; sourceHandle: ConnectionSourceHandle } | null {
  if (!connection.source || !connection.target) return null;
  const sourceIsGateway = connection.source === snapshot.gateway.id;
  const targetIsGateway = connection.target === snapshot.gateway.id;
  if (sourceIsGateway === targetIsGateway) return null;
  const connectionId = sourceIsGateway ? connection.target : connection.source;
  if (!snapshot.nodes.some((node) => node.id === connectionId)) return null;
  const sourceHandle = asConnectionSourceHandle(
    sourceIsGateway ? connection.targetHandle : connection.sourceHandle,
  );
  return sourceHandle ? { connectionId, sourceHandle } : null;
}

function deviceSourceHandle(position: Point, target: Point = { x: 0, y: 0 }): string {
  const relative = { x: position.x - target.x, y: position.y - target.y };
  if (Math.abs(relative.x) >= Math.abs(relative.y)) {
    return relative.x < 0 ? "right" : "left";
  }
  return relative.y < 0 ? "bottom" : "top";
}

function assignedInterface(
  assignment: InterfaceAssignment | null | undefined,
): SdexInterfaceName | null {
  if (!assignment?.resolved) return null;
  return assignment.interface_name === "eth1" ||
    assignment.interface_name === "eth2"
    ? assignment.interface_name
    : null;
}

function legacyAssignedInterface(node: ConnectionNode): SdexInterfaceName | null {
  if (node.interface_assignment !== undefined) {
    return assignedInterface(node.interface_assignment);
  }
  return node.network_interface === "eth1" || node.network_interface === "eth2"
    ? node.network_interface
    : null;
}

function visualElements(snapshot: TopologySnapshot): VisualElement[] {
  return snapshot.visual_topology?.elements ?? [];
}

function memberships(snapshot: TopologySnapshot): RackMembership[] {
  return snapshot.visual_topology?.rack_memberships ?? [];
}

function rackView(
  rack: RackElement,
  rackMemberships: RackMembership[],
): RackElementView {
  const slotAssignments: RackSlotView[] = rackMemberships.map((membership) => ({
    row: membership.row,
    column: membership.column,
    connection_id: membership.connection_id,
  }));
  return {
    id: rack.id,
    type: "rack",
    name: rack.name,
    rows: rack.rows,
    columns: rack.columns,
    capacity: rack.capacity,
    position: rack.position,
    width: rack.width,
    height: rack.height,
    member_ids: rackMemberships.map((membership) => membership.connection_id),
    slot_assignments: slotAssignments,
    collapsed: rack.collapsed,
    external_interface: rack.external_interface,
    schema_version: rack.schema_version,
    created_at: rack.created_at,
    updated_at: rack.updated_at,
  };
}

function handleSide(handle: string | null | undefined, fallback: "left" | "right") {
  if (handle?.toLowerCase().includes("left")) return "left" as const;
  if (handle?.toLowerCase().includes("right")) return "right" as const;
  return fallback;
}

function isNewSwitchHandle(handle: string | null | undefined): boolean {
  return handle === "left:new" || handle === "right:new";
}

export function stableSwitchHandleId(
  handle: string | null | undefined,
  fallbackSide: "left" | "right",
  linkId: string,
): string {
  const side = handleSide(handle, fallbackSide);
  return !handle || isNewSwitchHandle(handle) ? `${side}:${linkId}` : handle;
}

export function persistableVisualHandle(
  handle: string | null | undefined,
): string | null | undefined {
  // `ConnectionMode.Loose` allows either lateral Switch handle to be used at
  // either end of a connection. Keep the placeholder's side in the create
  // payload so the API can turn it into a link-specific persisted handle.
  return handle;
}

export function visualLinkHandlesForCreate(
  connection: Pick<Connection, "sourceHandle" | "targetHandle">,
  reverse: boolean,
): Pick<VisualLinkCreate, "source_handle" | "target_handle"> {
  return {
    source_handle: reverse
      ? persistableVisualHandle(connection.targetHandle)
      : persistableVisualHandle(connection.sourceHandle),
    target_handle: reverse
      ? persistableVisualHandle(connection.sourceHandle)
      : persistableVisualHandle(connection.targetHandle),
  };
}

function switchHandles(
  visualSwitch: VisualSwitch,
  snapshot: TopologySnapshot,
): SwitchHandleView[] {
  const handles = new Map<string, SwitchHandleView>();
  for (const link of snapshot.visual_topology?.links ?? []) {
    if (link.source === visualSwitch.id) {
      const id = stableSwitchHandleId(link.source_handle, "right", link.id);
      handles.set(id, {
        id,
        side: handleSide(id, "right"),
        type: "source",
        label: `Visual link ${link.id}`,
      });
    }
    if (link.target === visualSwitch.id) {
      const id = stableSwitchHandleId(link.target_handle, "left", link.id);
      handles.set(id, {
        id,
        side: handleSide(id, "left"),
        type: "target",
        label: `Visual link ${link.id}`,
      });
    }
  }
  handles.set("left:new", {
    id: "left:new",
    side: "left",
    type: "target",
    label: "New left connection",
  });
  handles.set("right:new", {
    id: "right:new",
    side: "right",
    type: "source",
    label: "New right connection",
  });
  return [...handles.values()];
}

interface BuildNodeOptions {
  onOpenVisual?: (element: VisualElement) => void;
}

export function buildNodes(
  snapshot: TopologySnapshot,
  positions: Record<string, Point>,
  editorEnabled: boolean,
  showNotEnabled: boolean,
  onOpen: (node: ConnectionNode) => void,
  options: BuildNodeOptions = {},
): ConnectMapFlowNode[] {
  const onOpenVisual = options.onOpenVisual ?? (() => undefined);
  const allMemberships = memberships(snapshot);
  const membershipByConnection = new Map(
    allMemberships.map((membership) => [membership.connection_id, membership]),
  );
  const sourceNodes = new Map(snapshot.nodes.map((node) => [node.id, node]));

  const rackNodes: ConnectMapFlowNode[] = visualElements(snapshot)
    .filter((element): element is RackElement => element.type === "rack")
    .map((rack) => {
      const rackMemberships = allMemberships.filter(
        (membership) => membership.rack_id === rack.id,
      );
      const dimensions = rackDimensions(rack.rows, rack.columns);
      return {
        id: rack.id,
        type: "rack",
        position: rack.position,
        data: {
          rack: rackView(rack, rackMemberships),
          editorEnabled,
          aggregateStatus: rack.aggregate.status,
          aggregateCounts: rack.aggregate,
          missingMemberIds: rackMemberships
            .filter((membership) => membership.missing)
            .map((membership) => membership.connection_id),
          highlightedSlot: null,
          onOpen: () => onOpenVisual(rack),
        },
        style: { width: dimensions.width, height: dimensions.height },
        draggable: editorEnabled,
        selectable: true,
        focusable: false,
        deletable: false,
        zIndex: 3,
      };
    });

  const switchNodes: ConnectMapFlowNode[] = visualElements(snapshot)
    .filter((element): element is VisualSwitch => element.type === "switch")
    .map((visualSwitch) => ({
      id: visualSwitch.id,
      type: "switch",
      position: visualSwitch.position,
      data: {
        visualSwitch,
        editorEnabled,
        handles: switchHandles(visualSwitch, snapshot),
        onOpen: () => onOpenVisual(visualSwitch),
      },
      draggable: editorEnabled,
      selectable: true,
      focusable: false,
      deletable: false,
      zIndex: 4,
    }));

  const gateway: ConnectMapFlowNode = {
    id: snapshot.gateway.id,
    type: "gateway",
    position: { x: 0, y: 0 },
    data: {
      connection: snapshot.gateway,
      onOpen,
      networkInterfaces: snapshot.network_interfaces,
    },
    draggable: false,
    selectable: true,
    focusable: false,
    deletable: false,
    zIndex: 5,
  };

  const external: ConnectMapFlowNode[] = snapshot.nodes
    .filter((node) => !membershipByConnection.has(node.id))
    .filter((node) => showNotEnabled || node.enabled)
    .map((node) => ({
      id: node.id,
      type: "connection",
      position: positions[node.id] ?? { x: 320, y: 0 },
      data: {
        connection: node,
        editorEnabled,
        variant: "standalone",
        onOpen,
      },
      draggable: editorEnabled,
      selectable: true,
      focusable: false,
      deletable: false,
      zIndex: 4,
      className: node.enabled ? undefined : "flow-node-disabled",
    }));

  const embedded: ConnectMapFlowNode[] = allMemberships.flatMap((membership) => {
    const node = membership.connection ?? sourceNodes.get(membership.connection_id);
    if (!node || (!showNotEnabled && !node.enabled)) return [];
    return [
      {
        id: node.id,
        type: "connection",
        parentId: membership.rack_id,
        position: rackSlotPosition(membership.row, membership.column),
        data: {
          connection: node,
          editorEnabled,
          variant: "embedded",
          rackId: membership.rack_id,
          onOpen,
        },
        draggable: editorEnabled,
        selectable: true,
        focusable: false,
        deletable: false,
        zIndex: 6,
        className: node.enabled ? "rack-member-node" : "rack-member-node flow-node-disabled",
      },
    ];
  });

  // React Flow requires parent nodes to precede their children.
  return [...rackNodes, ...switchNodes, gateway, ...external, ...embedded];
}

function entityPosition(
  id: string,
  snapshot: TopologySnapshot,
  positions: Record<string, Point>,
): Point {
  if (id === snapshot.gateway.id) return { x: 0, y: 0 };
  const visual = visualElements(snapshot).find((element) => element.id === id);
  return visual?.position ?? positions[id] ?? { x: 0, y: 0 };
}

function edgeStatus(
  edge: TopologyEdge,
  nodeById: Map<string, ConnectionNode>,
): { status: ConnectionNode["status"]; reason: string | null; stale: boolean } {
  const aggregate = edge.aggregate;
  if (aggregate) {
    return {
      status: aggregate.status,
      reason: `${aggregate.connected} connected, ${aggregate.disconnected} disconnected, ${aggregate.unknown} unknown, ${aggregate.disabled} disabled`,
      stale: aggregate.missing > 0,
    };
  }
  const source = nodeById.get(edge.source);
  return {
    status: source?.status ?? "unknown",
    reason: source?.status_reason ?? null,
    stale: source?.stale ?? false,
  };
}

function edgeName(edge: TopologyEdge, snapshot: TopologySnapshot): string {
  const sourceNode = snapshot.nodes.find((node) => node.id === edge.source);
  if (sourceNode) return sourceNode.display_name;
  const sourceVisual = visualElements(snapshot).find(
    (element) => element.id === edge.source,
  );
  return sourceVisual?.name ?? "Topology element";
}

interface BuildEdgeOptions {
  editorEnabled?: boolean;
  onSaveRoute?: (
    edgeId: string,
    update: EdgeRouteUpdate,
  ) => Promise<EdgeRoute | void>;
  onResetRoute?: (edgeId: string) => Promise<void>;
}

export function buildEdges(
  snapshot: TopologySnapshot,
  positions: Record<string, Point>,
  showNotEnabled: boolean,
  onConfigureEdge: (edgeId: string) => void = () => undefined,
  options: BuildEdgeOptions = {},
): DataCableFlowEdge[] {
  const nodeById = new Map(snapshot.nodes.map((node) => [node.id, node]));
  const canonical: TopologyEdge[] =
    snapshot.edges ??
    snapshot.nodes.flatMap((node) => {
      const interfaceName = legacyAssignedInterface(node);
      if (!interfaceName) return [];
      return [{
        id: edgeIdForConnection(node.id),
        source: node.id,
        target: snapshot.gateway.id,
        source_handle: null,
        target_handle: `sdex-${interfaceName}`,
        interface_assignment: node.interface_assignment ?? {
          resolved: true,
          interface_name: interfaceName,
          source: "unresolved",
          reason: "Legacy topology snapshot.",
        },
        style: snapshot.edge_styles?.[edgeIdForConnection(node.id)] ?? null,
      }];
    });

  return canonical.flatMap((edge) => {
    const sourceNode = nodeById.get(edge.source);
    if (sourceNode && (!sourceNode.enabled || (!showNotEnabled && !sourceNode.enabled))) {
      return [];
    }
    const assigned = assignedInterface(edge.interface_assignment);
    const hinted =
      edge.interface_assignment.interface_name === "eth1" ||
      edge.interface_assignment.interface_name === "eth2"
        ? edge.interface_assignment.interface_name
        : null;
    const interfaceName: SdexInterfaceName | null = assigned ?? hinted;
    if (!interfaceName) return [];
    const sourcePosition = entityPosition(edge.source, snapshot, positions);
    const targetPosition = entityPosition(edge.target, snapshot, positions);
    const sourceVisual = visualElements(snapshot).find(
      (element) => element.id === edge.source,
    );
    const targetIsGateway = edge.target === snapshot.gateway.id;
    const sourceHandle =
      sourceVisual?.type === "switch"
        ? stableSwitchHandleId(
            edge.source_handle,
            sourcePosition.x <= targetPosition.x ? "right" : "left",
            edge.id,
          )
        : edge.source_handle ??
          (sourceVisual?.type === "rack"
            ? sourcePosition.x <= targetPosition.x
              ? "rack-right"
              : "rack-left"
            : deviceSourceHandle(sourcePosition, targetPosition));
    const targetVisual = visualElements(snapshot).find(
      (element) => element.id === edge.target,
    );
    const targetHandle = targetIsGateway
      ? `sdex-${interfaceName}`
      : targetVisual?.type === "switch"
        ? stableSwitchHandleId(
            edge.target_handle,
            targetPosition.x <= sourcePosition.x ? "right" : "left",
            edge.id,
          )
        : edge.target_handle;
    const semantic = edgeStatus(edge, nodeById);
    const route: EdgeRoute | null =
      edge.route ?? snapshot.visual_topology?.routes[edge.id] ?? null;
    const style: EdgeVisualStyle | null =
      edge.style ?? snapshot.edge_styles?.[edge.id] ?? null;
    const aggregate = edge.aggregate ?? null;
    return [{
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle,
      targetHandle,
      type: "dataCable",
      reconnectable:
        (options.editorEnabled ?? false) &&
        targetIsGateway &&
        edge.id === edgeIdForConnection(edge.source),
      selectable: true,
      focusable: true,
      deletable: false,
      ariaRole: "button",
      ariaLabel: `Configure cable from ${edgeName(edge, snapshot)} through ${interfaceName}`,
      domAttributes: {
        "aria-describedby": undefined,
        onKeyDown: (event: ReactKeyboardEvent<SVGGElement>) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          event.stopPropagation();
          onConfigureEdge(edge.id);
        },
      },
      zIndex: 1,
      data: {
        status: semantic.status,
        reason: semantic.reason,
        stale: snapshot.stale || semantic.stale,
        style,
        connectionName: edgeName(edge, snapshot),
        networkInterface: interfaceName,
        onConfigure: onConfigureEdge,
        route,
        editorEnabled: options.editorEnabled ?? false,
        aggregate,
        flowAnimated: aggregate?.animated ?? semantic.status === "connected",
        onSaveRoute: options.onSaveRoute,
        onResetRoute: options.onResetRoute,
      },
    }];
  });
}

export interface TopologyCanvasProps {
  snapshot: TopologySnapshot;
  editorEnabled: boolean;
  showNotEnabled: boolean;
  onSelectNode: (node: ConnectionNode) => void;
  onSelectVisual?: (element: VisualElement) => void;
  onConfigureEdge: (edgeId: string) => void;
  onSaveLayout: (update: LayoutUpdate) => Promise<void>;
  onResetLayout: () => Promise<void>;
  onCreateVisualElement?: (payload: VisualElementCreate) => Promise<VisualElement>;
  onUpdateVisualElement?: (
    elementId: string,
    update: { position: Point },
  ) => Promise<VisualElement>;
  onDeleteVisualElement?: (
    elementId: string,
    options?: { leaveUnrouted?: boolean },
  ) => Promise<void>;
  onAddRackMember?: (
    rackId: string,
    connectionId: string,
    row: number,
    column: number,
    allowUnresolvedInterface?: boolean,
  ) => Promise<void>;
  onRemoveRackMember?: (rackId: string, connectionId: string) => Promise<void>;
  onCreateVisualLink?: (payload: VisualLinkCreate) => Promise<unknown>;
  onReanchorConnection?: (
    connectionId: string,
    sourceHandle: ConnectionSourceHandle,
  ) => Promise<void>;
  onSaveEdgeRoute?: (
    edgeId: string,
    update: EdgeRouteUpdate,
  ) => Promise<EdgeRoute | void>;
  onResetEdgeRoute?: (edgeId: string) => Promise<void>;
  onNotify?: (message: string) => void;
  canUndo?: boolean;
  canRedo?: boolean;
  historyBusy?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
}

function TopologyCanvasInner({
  snapshot,
  editorEnabled,
  showNotEnabled,
  onSelectNode,
  onSelectVisual = () => undefined,
  onConfigureEdge,
  onSaveLayout,
  onResetLayout,
  onCreateVisualElement,
  onUpdateVisualElement,
  onDeleteVisualElement,
  onAddRackMember,
  onRemoveRackMember,
  onCreateVisualLink,
  onReanchorConnection,
  onSaveEdgeRoute,
  onResetEdgeRoute,
  onNotify,
  canUndo,
  canRedo,
  historyBusy,
  onUndo,
  onRedo,
}: TopologyCanvasProps) {
  const flow = useReactFlow<ConnectMapFlowNode, DataCableFlowEdge>();
  const completeLayout = useMemo(() => withCompleteLayout(snapshot), [snapshot]);
  const positionCache = useRef<Record<string, Point>>(completeLayout.positions);
  const buildNodeOptions = useMemo(
    () => ({ onOpenVisual: onSelectVisual }),
    [onSelectVisual],
  );
  const buildEdgeOptions = useMemo(
    () => ({
      editorEnabled,
      onSaveRoute: onSaveEdgeRoute
        ? async (edgeId: string, update: EdgeRouteUpdate) => {
            return await onSaveEdgeRoute(edgeId, update);
          }
        : undefined,
      onResetRoute: onResetEdgeRoute,
    }),
    [editorEnabled, onResetEdgeRoute, onSaveEdgeRoute],
  );
  const initialNodes = useMemo(
    () =>
      buildNodes(
        snapshot,
        completeLayout.positions,
        editorEnabled,
        showNotEnabled,
        onSelectNode,
        buildNodeOptions,
      ),
    // Controlled state owns the live graph after initialization.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const initialEdges = useMemo(
    () =>
      buildEdges(
        snapshot,
        completeLayout.positions,
        showNotEnabled,
        onConfigureEdge,
        buildEdgeOptions,
      ),
    // Controlled state owns the live graph after initialization.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [nodes, setNodes, onNodesChange] =
    useNodesState<ConnectMapFlowNode>(initialNodes);
  const [edges, setEdges, onEdgesChange] =
    useEdgesState<DataCableFlowEdge>(initialEdges);
  const [confirmReset, setConfirmReset] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<VisualElement | null>(null);
  const [pendingInterfaceAction, setPendingInterfaceAction] = useState<
    | {
        kind: "rack";
        rackId: string;
        rackName: string;
        connectionId: string;
        connectionName: string;
        row: number;
        column: number;
        interfaceName: SdexInterfaceName;
      }
    | {
        kind: "link";
        payload: VisualLinkCreate;
        connectionName: string;
        interfaceName: SdexInterfaceName;
      }
    | null
  >(null);
  const [pendingInterfaceBusy, setPendingInterfaceBusy] = useState(false);
  const [pendingInterfaceError, setPendingInterfaceError] = useState<string | null>(
    null,
  );
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<VisualTool | null>(null);
  const initializedSnapshot = useRef<string | null>(null);
  const initialFitApplied = useRef(false);
  const pendingVisualSelection = useRef<string | null>(null);
  const nodesInitialized = useNodesInitialized();
  const hasSavedViewport = snapshot.layout?.viewport != null;
  const defaultViewport: Viewport = hasSavedViewport
    ? (snapshot.layout.viewport ?? completeLayout.viewport)
    : completeLayout.viewport;

  useEffect(() => {
    const draggingNodeIds = new Set(
      nodes.filter((node) => node.dragging).map((node) => node.id),
    );
    for (const [id, position] of Object.entries(completeLayout.positions)) {
      if (!draggingNodeIds.has(id)) positionCache.current[id] = position;
    }
    positionCache.current[snapshot.gateway.id] = { x: 0, y: 0 };
    const selectedNodes = new Set(nodes.filter((node) => node.selected).map((node) => node.id));
    const selectedEdges = new Set(edges.filter((edge) => edge.selected).map((edge) => edge.id));
    const rebuiltNodes = buildNodes(
        snapshot,
        positionCache.current,
        editorEnabled,
        showNotEnabled,
        onSelectNode,
        buildNodeOptions,
      );
    const pendingId = pendingVisualSelection.current;
    if (pendingId && rebuiltNodes.some((node) => node.id === pendingId)) {
      selectedNodes.clear();
      selectedNodes.add(pendingId);
      pendingVisualSelection.current = null;
    }
    setNodes(
      rebuiltNodes.map((node) => ({
        ...node,
        selected: selectedNodes.has(node.id),
      })),
    );
    setEdges(
      buildEdges(
        snapshot,
        positionCache.current,
        showNotEnabled,
        onConfigureEdge,
        buildEdgeOptions,
      ).map((edge) => ({ ...edge, selected: selectedEdges.has(edge.id) })),
    );
    // Selection is deliberately captured at the snapshot boundary only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    completeLayout.positions,
    editorEnabled,
    onConfigureEdge,
    onSelectNode,
    setEdges,
    setNodes,
    showNotEnabled,
    snapshot,
    buildNodeOptions,
    buildEdgeOptions,
  ]);

  useEffect(() => {
    const missing = snapshot.nodes.filter(
      (node) => snapshot.layout?.positions?.[node.id] === undefined,
    );
    const signature = missing.map((node) => node.id).sort().join("|");
    if (!signature || initializedSnapshot.current === signature) return;
    initializedSnapshot.current = signature;
    void onSaveLayout({
      positions: missing.map((node) => ({
        node_id: node.id,
        x: positionCache.current[node.id]?.x ?? 0,
        y: positionCache.current[node.id]?.y ?? 0,
      })),
    }).catch(() => {
      initializedSnapshot.current = null;
    });
  }, [onSaveLayout, snapshot.layout?.positions, snapshot.nodes]);

  const clearRackHighlight = useCallback(() => {
    setNodes((current) =>
      current.map((candidate) =>
        candidate.type === "rack" && candidate.data.highlightedSlot
          ? { ...candidate, data: { ...candidate.data, highlightedSlot: null } }
          : candidate,
      ),
    );
  }, [setNodes]);

  const firstOpenSlot = useCallback(
    (rackId: string): { row: number; column: number } | null => {
      const rack = visualElements(snapshot).find(
        (element): element is RackElement =>
          element.id === rackId && element.type === "rack",
      );
      if (!rack) return null;
      const occupied = new Set(
        memberships(snapshot)
          .filter((membership) => membership.rack_id === rackId)
          .map((membership) => `${membership.row}:${membership.column}`),
      );
      for (let row = 0; row < rack.rows; row += 1) {
        for (let column = 0; column < rack.columns; column += 1) {
          if (!occupied.has(`${row}:${column}`)) return { row, column };
        }
      }
      return null;
    },
    [snapshot],
  );

  const slotAtPoint = useCallback(
    (rackId: string, point: Point): { row: number; column: number } | null => {
      const rack = visualElements(snapshot).find(
        (element): element is RackElement =>
          element.id === rackId && element.type === "rack",
      );
      const rackPosition = flow.getInternalNode(rackId)?.internals.positionAbsolute;
      if (!rack || !rackPosition) return firstOpenSlot(rackId);
      const relativeX = point.x - rackPosition.x - RACK_PADDING_X;
      const relativeY =
        point.y - rackPosition.y - RACK_HEADER_HEIGHT - RACK_CONTENT_PADDING_TOP;
      const column = Math.floor(
        relativeX / (EMBEDDED_CONNECTION_WIDTH + RACK_SLOT_GAP),
      );
      const row = Math.floor(
        relativeY / (EMBEDDED_CONNECTION_HEIGHT + RACK_SLOT_GAP),
      );
      const withinCell =
        relativeX >= 0 &&
        relativeY >= 0 &&
        column >= 0 &&
        column < rack.columns &&
        row >= 0 &&
        row < rack.rows &&
        relativeX % (EMBEDDED_CONNECTION_WIDTH + RACK_SLOT_GAP) <=
          EMBEDDED_CONNECTION_WIDTH &&
        relativeY % (EMBEDDED_CONNECTION_HEIGHT + RACK_SLOT_GAP) <=
          EMBEDDED_CONNECTION_HEIGHT;
      if (!withinCell) return firstOpenSlot(rackId);
      const occupied = memberships(snapshot).some(
        (membership) =>
          membership.rack_id === rackId &&
          membership.row === row &&
          membership.column === column,
      );
      return occupied ? firstOpenSlot(rackId) : { row, column };
    },
    [firstOpenSlot, flow, snapshot],
  );

  const absolutePosition = useCallback(
    (node: ConnectMapFlowNode): Point =>
      flow.getInternalNode(node.id)?.internals.positionAbsolute ?? node.position,
    [flow],
  );

  const restorePersistedGraph = useCallback(() => {
    setNodes((current) => {
      const selected = new Set(
        current.filter((node) => node.selected).map((node) => node.id),
      );
      return buildNodes(
        snapshot,
        positionCache.current,
        editorEnabled,
        showNotEnabled,
        onSelectNode,
        buildNodeOptions,
      ).map((node) => ({ ...node, selected: selected.has(node.id) }));
    });
    setEdges((current) => {
      const selected = new Set(
        current.filter((edge) => edge.selected).map((edge) => edge.id),
      );
      return buildEdges(
        snapshot,
        positionCache.current,
        showNotEnabled,
        onConfigureEdge,
        buildEdgeOptions,
      ).map((edge) => ({ ...edge, selected: selected.has(edge.id) }));
    });
  }, [
    buildEdgeOptions,
    buildNodeOptions,
    editorEnabled,
    onConfigureEdge,
    onSelectNode,
    setEdges,
    setNodes,
    showNotEnabled,
    snapshot,
  ]);

  const onDragStop = useCallback(
    (event: React.MouseEvent, node: ConnectMapFlowNode) => {
      clearRackHighlight();
      if (node.type === "gateway") return;
      if (node.type === "rack" || node.type === "switch") {
        const previous = positionCache.current[node.id];
        positionCache.current[node.id] = node.position;
        void onUpdateVisualElement?.(node.id, { position: node.position }).catch(() => {
          if (previous) positionCache.current[node.id] = previous;
          restorePersistedGraph();
        });
        return;
      }
      const absolute = absolutePosition(node);
      if (node.parentId && node.data.rackId) {
        const parent = flow.getInternalNode(node.parentId);
        const parentPosition = parent?.internals.positionAbsolute;
        const parentWidth = parent?.measured.width ?? 0;
        const parentHeight = parent?.measured.height ?? 0;
        const childWidth = flow.getInternalNode(node.id)?.measured.width ?? 0;
        const childHeight = flow.getInternalNode(node.id)?.measured.height ?? 0;
        const center = {
          x: absolute.x + childWidth / 2,
          y: absolute.y + childHeight / 2,
        };
        const remainsInside =
          parentPosition &&
          center.x >= parentPosition.x &&
          center.x <= parentPosition.x + parentWidth &&
          center.y >= parentPosition.y &&
          center.y <= parentPosition.y + parentHeight;
        if (!remainsInside) {
          void (async () => {
            await onRemoveRackMember?.(node.data.rackId ?? node.parentId ?? "", node.id);
            await onSaveLayout(positionLayoutUpdate(node.id, absolute));
            positionCache.current[node.id] = absolute;
          })().catch(restorePersistedGraph);
        }
        return;
      }

      const intersectingRack = flow
        .getIntersectingNodes(node)
        .find((candidate) => candidate.type === "rack");
      if (intersectingRack && onAddRackMember) {
        const slot = slotAtPoint(
          intersectingRack.id,
          flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }),
        );
        if (slot) {
          const connection = snapshot.nodes.find((item) => item.id === node.id);
          const rack = visualElements(snapshot).find(
            (element): element is RackElement =>
              element.id === intersectingRack.id && element.type === "rack",
          );
          if (connection && legacyAssignedInterface(connection) === null) {
            restorePersistedGraph();
            if (!rack?.external_interface) {
              onNotify?.(
                "Select the Rack external interface before adding a connection whose interface is unresolved.",
              );
              if (rack) onSelectVisual(rack);
              return;
            }
            setPendingInterfaceError(null);
            setPendingInterfaceAction({
              kind: "rack",
              rackId: rack.id,
              rackName: rack.name,
              connectionId: connection.id,
              connectionName: connection.display_name,
              row: slot.row,
              column: slot.column,
              interfaceName: rack.external_interface,
            });
            return;
          }
          void onAddRackMember(
            intersectingRack.id,
            node.id,
            slot.row,
            slot.column,
            false,
          ).catch(restorePersistedGraph);
          return;
        }
        onNotify?.("That Rack is full. Increase its rows or columns first.");
        restorePersistedGraph();
        return;
      }
      void onSaveLayout(positionLayoutUpdate(node.id, node.position))
        .then(() => {
          positionCache.current[node.id] = node.position;
        })
        .catch(restorePersistedGraph);
    },
    [
      absolutePosition,
      clearRackHighlight,
      flow,
      onAddRackMember,
      onRemoveRackMember,
      onSaveLayout,
      onUpdateVisualElement,
      onNotify,
      onSelectVisual,
      restorePersistedGraph,
      slotAtPoint,
      snapshot,
    ],
  );

  const onNodeDrag = useCallback(
    (event: React.MouseEvent, node: ConnectMapFlowNode) => {
      if (node.type !== "connection" || node.parentId) return;
      const rack = flow
        .getIntersectingNodes(node)
        .find((candidate) => candidate.type === "rack");
      const slot = rack
        ? slotAtPoint(
            rack.id,
            flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }),
          )
        : null;
      setNodes((current) =>
        current.map((candidate) =>
          candidate.type === "rack"
            ? {
                ...candidate,
                data: {
                  ...candidate.data,
                  highlightedSlot: candidate.id === rack?.id ? slot : null,
                },
              }
            : candidate,
        ),
      );
    },
    [flow, setNodes, slotAtPoint],
  );

  const onMoveEnd: OnMoveEnd = useCallback(
    (_event, viewport) => {
      void onSaveLayout({ viewport }).catch(() => undefined);
    },
    [onSaveLayout],
  );

  const resetView = useCallback(() => {
    void flow.setCenter(108, 112, { zoom: 1, duration: 450 });
  }, [flow]);

  const fitTopology = useCallback(() => {
    const padding =
      window.innerWidth >= 900
        ? ({ top: "6%", right: "4%", bottom: "10%", left: "300px" } as const)
        : ("8%" as const);
    void flow.fitView({ padding, minZoom: 0.22, maxZoom: 1.1, duration: 450 });
  }, [flow]);

  useEffect(() => {
    if (hasSavedViewport || !nodesInitialized || initialFitApplied.current) return;
    initialFitApplied.current = true;
    const frame = window.requestAnimationFrame(fitTopology);
    return () => window.cancelAnimationFrame(frame);
  }, [fitTopology, hasSavedViewport, nodesInitialized]);

  useEffect(() => {
    if (!editorEnabled) {
      setActiveTool(null);
      setPendingDelete(null);
      setPendingInterfaceAction(null);
      setPendingInterfaceError(null);
    }
  }, [editorEnabled]);

  useEffect(() => {
    if (!editorEnabled) return undefined;
    const handleKeyboard = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        (target instanceof HTMLElement && target.isContentEditable)
      ) {
        return;
      }
      if (event.key === "Escape") {
        setActiveTool(null);
        setNodes((current) => current.map((node) => ({ ...node, selected: false })));
        setEdges((current) => current.map((edge) => ({ ...edge, selected: false })));
        return;
      }
      if (event.key !== "Delete") return;
      const selected = flow
        .getNodes()
        .find(
          (node) =>
            node.selected &&
            (node.type === "rack" || node.type === "switch"),
        );
      if (!selected) return;
      const element = visualElements(snapshot).find(
        (candidate) => candidate.id === selected.id,
      );
      if (!element) return;
      event.preventDefault();
      setPendingDelete(element);
    };
    document.addEventListener("keydown", handleKeyboard);
    return () => document.removeEventListener("keydown", handleKeyboard);
  }, [editorEnabled, flow, setEdges, setNodes, snapshot]);

  const createAt = useCallback(
    (tool: VisualTool, position: Point) => {
      if (!onCreateVisualElement) return;
      setActiveTool(tool);
      void onCreateVisualElement({
        type: tool,
        position,
        name: tool === "rack" ? "New Rack" : "New Switch",
        ...(tool === "rack" ? { rows: 1, columns: 3 } : {}),
      })
        .then((created) => {
          pendingVisualSelection.current = created.id;
          setNodes((current) =>
            current.map((node) => ({
              ...node,
              selected: node.id === created.id,
            })),
          );
          setEdges((current) =>
            current.map((edge) =>
              edge.selected ? { ...edge, selected: false } : edge,
            ),
          );
        })
        .catch(() => undefined)
        .finally(() => setActiveTool(null));
    },
    [onCreateVisualElement, setEdges, setNodes],
  );

  const createAtVisibleCenter = useCallback(
    (tool: VisualTool) => {
      const bounds = document
        .querySelector<HTMLElement>(".topology-canvas .react-flow")
        ?.getBoundingClientRect();
      const screen = bounds
        ? { x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 }
        : { x: window.innerWidth / 2, y: window.innerHeight / 2 };
      createAt(tool, flow.screenToFlowPosition(screen));
    },
    [createAt, flow],
  );

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      const tool = readVisualToolDrag(event.dataTransfer);
      if (!tool || !editorEnabled) return;
      event.preventDefault();
      createAt(
        tool,
        flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }),
      );
    },
    [createAt, editorEnabled, flow],
  );

  const interfaceForConnection = useCallback(
    (connection: Connection): SdexInterfaceName | null => {
      if (connection.target === snapshot.gateway.id) {
        return connection.targetHandle === "sdex-eth2" ? "eth2" : "eth1";
      }
      if (connection.source === snapshot.gateway.id) {
        return connection.sourceHandle === "sdex-eth2" ? "eth2" : "eth1";
      }
      const source = snapshot.nodes.find((node) => node.id === connection.source);
      const target = snapshot.nodes.find((node) => node.id === connection.target);
      return (
        legacyAssignedInterface(source ?? target ?? snapshot.gateway) ??
        visualElements(snapshot).find(
          (element) =>
            element.id === connection.source || element.id === connection.target,
        )?.external_interface ??
        null
      );
    },
    [snapshot],
  );

  const connectVisual = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const reanchor = directConnectionReanchor(connection, snapshot);
      if (reanchor && onReanchorConnection) {
        void onReanchorConnection(
          reanchor.connectionId,
          reanchor.sourceHandle,
        ).catch(() => undefined);
        return;
      }
      if (!onCreateVisualLink) return;
      const externalInterface = interfaceForConnection(connection);
      if (!externalInterface) {
        onNotify?.(
          "Select an eth1 or eth2 interface before creating this visual link.",
        );
        return;
      }
      const elementType = (id: string) =>
        id === snapshot.gateway.id
          ? "gateway"
          : visualElements(snapshot).find((element) => element.id === id)?.type ??
            "connection";
      const rank = (type: string) =>
        type === "gateway" ? 3 : type === "switch" ? 2 : 1;
      const reverse =
        rank(elementType(connection.source)) >
        rank(elementType(connection.target));
      const payload: VisualLinkCreate = {
        source: reverse ? connection.target : connection.source,
        target: reverse ? connection.source : connection.target,
        ...visualLinkHandlesForCreate(connection, reverse),
        external_interface: externalInterface,
      };
      const sourceNode = snapshot.nodes.find((node) => node.id === payload.source);
      if (sourceNode && legacyAssignedInterface(sourceNode) === null) {
        setPendingInterfaceError(null);
        setPendingInterfaceAction({
          kind: "link",
          payload,
          connectionName: sourceNode.display_name,
          interfaceName: externalInterface,
        });
        return;
      }
      void onCreateVisualLink(payload).catch(() => undefined);
    },
    [
      interfaceForConnection,
      onCreateVisualLink,
      onNotify,
      onReanchorConnection,
      snapshot,
    ],
  );

  const reconnectDirectCable = useCallback(
    (edge: DataCableFlowEdge, connection: Connection) => {
      if (!editorEnabled || !onReanchorConnection) return;
      const expectedConnectionId = edge.id.startsWith("sdex-to-")
        ? edge.id.slice("sdex-to-".length)
        : null;
      const reanchor = directConnectionReanchor(connection, snapshot);
      if (!reanchor || reanchor.connectionId !== expectedConnectionId) {
        onNotify?.("A real SDEX cable endpoint can only move to another side of the same device.");
        return;
      }
      void onReanchorConnection(
        reanchor.connectionId,
        reanchor.sourceHandle,
      ).catch(() => undefined);
    },
    [editorEnabled, onNotify, onReanchorConnection, snapshot],
  );

  const performResetLayout = async () => {
    setResetting(true);
    setResetError(null);
    try {
      await onResetLayout();
      const positions = createRadialPositions(snapshot.nodes);
      positions[snapshot.gateway.id] = { x: 0, y: 0 };
      positionCache.current = positions;
      setNodes(
        buildNodes(
          snapshot,
          positions,
          editorEnabled,
          showNotEnabled,
          onSelectNode,
          buildNodeOptions,
        ),
      );
      setEdges(
        buildEdges(
          snapshot,
          positions,
          showNotEnabled,
          onConfigureEdge,
          buildEdgeOptions,
        ),
      );
      await onSaveLayout({
        positions: snapshot.nodes.map((node) => ({
          node_id: node.id,
          x: positions[node.id]?.x ?? 0,
          y: positions[node.id]?.y ?? 0,
        })),
      });
      setConfirmReset(false);
      window.requestAnimationFrame(fitTopology);
    } catch (error) {
      setResetError(
        error instanceof Error ? error.message : "The layout could not be reset.",
      );
    } finally {
      setResetting(false);
    }
  };

  return (
    <div
      className={`topology-canvas${editorEnabled ? " editor-active" : ""}`}
      onDragOver={(event) => {
        if (!editorEnabled) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={handleDrop}
    >
      <ReactFlow<ConnectMapFlowNode, DataCableFlowEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDoubleClick={(event, node) => {
          event.preventDefault();
          event.stopPropagation();
          if (node.type === "connection" || node.type === "gateway") {
            onSelectNode(node.data.connection);
            return;
          }
          const visual = visualElements(snapshot).find(
            (element) => element.id === node.id,
          );
          if (visual) onSelectVisual(visual);
        }}
        onEdgeDoubleClick={(event, edge) => {
          event.preventDefault();
          event.stopPropagation();
          onConfigureEdge(edge.id);
        }}
        onNodeDrag={onNodeDrag}
        onNodeDragStop={onDragStop}
        onConnect={connectVisual}
        onReconnect={reconnectDirectCable}
        isValidConnection={(connection) =>
          editorEnabled &&
          Boolean(connection.source) &&
          Boolean(connection.target) &&
          connection.source !== connection.target
        }
        connectionMode={ConnectionMode.Loose}
        onMoveEnd={onMoveEnd}
        defaultViewport={defaultViewport}
        minZoom={0.18}
        maxZoom={2.25}
        zoomOnScroll
        zoomOnPinch
        zoomOnDoubleClick={false}
        panOnScroll={false}
        panOnDrag
        selectionOnDrag={false}
        nodesConnectable={editorEnabled}
        deleteKeyCode={null}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={22}
          size={1.25}
          className="canvas-background"
        />
      </ReactFlow>

      <EditorToolbar
        visible={editorEnabled}
        activeTool={activeTool}
        onCreate={createAtVisibleCenter}
        onToolDragStart={setActiveTool}
        onToolDragEnd={() => setActiveTool(null)}
        onCancel={() => setActiveTool(null)}
        canUndo={canUndo}
        canRedo={canRedo}
        historyBusy={historyBusy}
        onUndo={onUndo}
        onRedo={onRedo}
      />

      <CanvasControls
        onZoomIn={() => void flow.zoomIn({ duration: 180 })}
        onZoomOut={() => void flow.zoomOut({ duration: 180 })}
        onFit={fitTopology}
        onResetView={resetView}
        onResetLayout={() => setConfirmReset(true)}
      />

      {editorEnabled && (
        <div className="editor-indicator" role="status">
          <span />
          {"Editor active \u00b7 Drag cards into Racks \u00b7 Hold Ctrl for a 90\u00b0 bend"}
        </div>
      )}

      <Modal
        open={pendingInterfaceAction !== null}
        title="Confirm unresolved interface"
        eyebrow="Visual topology"
        size="small"
        onClose={() => {
          if (!pendingInterfaceBusy) setPendingInterfaceAction(null);
        }}
      >
        <div className="confirm-content">
          <p>
            SDEX did not report a resolved interface for{" "}
            <strong>{pendingInterfaceAction?.connectionName}</strong>. Confirm
            that this visual path should use{" "}
            <strong>{pendingInterfaceAction?.interfaceName}</strong>.
          </p>
          {pendingInterfaceAction?.kind === "rack" && (
            <p>
              The connection will occupy a slot in{" "}
              <strong>{pendingInterfaceAction.rackName}</strong>. This changes
              only ConnectMap presentation metadata.
            </p>
          )}
          {pendingInterfaceError && (
            <Notice tone="danger">{pendingInterfaceError}</Notice>
          )}
          <footer className="form-actions">
            <button
              className="button button-ghost"
              type="button"
              disabled={pendingInterfaceBusy}
              onClick={() => setPendingInterfaceAction(null)}
            >
              Cancel
            </button>
            <button
              className="button button-primary"
              type="button"
              disabled={pendingInterfaceBusy}
              onClick={() => {
                const action = pendingInterfaceAction;
                if (!action) return;
                setPendingInterfaceBusy(true);
                setPendingInterfaceError(null);
                const operation =
                  action.kind === "rack"
                    ? onAddRackMember?.(
                        action.rackId,
                        action.connectionId,
                        action.row,
                        action.column,
                        true,
                      )
                    : onCreateVisualLink?.({
                        ...action.payload,
                        allow_unresolved_interface: true,
                      });
                if (!operation) {
                  setPendingInterfaceBusy(false);
                  setPendingInterfaceError(
                    "The visual topology operation is not available.",
                  );
                  return;
                }
                void Promise.resolve(operation)
                  .then(() => setPendingInterfaceAction(null))
                  .catch((error: unknown) => {
                    restorePersistedGraph();
                    setPendingInterfaceError(
                      error instanceof Error
                        ? error.message
                        : "The interface confirmation could not be saved.",
                    );
                  })
                  .finally(() => setPendingInterfaceBusy(false));
              }}
            >
              {pendingInterfaceBusy ? "Saving\u2026" : "Confirm interface"}
            </button>
          </footer>
        </div>
      </Modal>

      <Modal
        open={confirmReset}
        title="Reset topology layout?"
        eyebrow="Layout"
        size="small"
        onClose={() => setConfirmReset(false)}
      >
        <div className="confirm-content">
          <p>
            Connection cards return to an automatic layout. Local Racks,
            Switches and cable routes are preserved.
          </p>
          {resetError && <Notice tone="danger">{resetError}</Notice>}
          <footer className="form-actions">
            <button
              className="button button-ghost"
              type="button"
              onClick={() => setConfirmReset(false)}
              disabled={resetting}
            >
              Keep current layout
            </button>
            <button
              className="button button-danger"
              type="button"
              onClick={() => void performResetLayout()}
              disabled={resetting}
            >
              {resetting ? "Resetting\u2026" : "Reset layout"}
            </button>
          </footer>
        </div>
      </Modal>

      <Modal
        open={pendingDelete !== null}
        title={`Delete ${pendingDelete?.type ?? "element"}?`}
        eyebrow="ConnectMap topology element"
        size="small"
        onClose={() => setPendingDelete(null)}
      >
        <div className="confirm-content">
          <p>
            This removes only the local visual element. Real SDEX connections
            and their operational data are never deleted.
          </p>
          {pendingDelete?.type === "switch" && (
            <p>
              Choose whether connected sources reconnect directly to SDEX or
              remain temporarily without a visual route.
            </p>
          )}
          <footer className="form-actions">
            <button
              className="button button-ghost"
              type="button"
              onClick={() => setPendingDelete(null)}
            >
              Cancel
            </button>
            {pendingDelete?.type === "switch" && (
              <button
                className="button button-ghost"
                type="button"
                onClick={() => {
                  const element = pendingDelete;
                  if (!element || !onDeleteVisualElement) return;
                  void onDeleteVisualElement(element.id, {
                    leaveUnrouted: true,
                  })
                    .then(() => setPendingDelete(null))
                    .catch(() => undefined);
                }}
              >
                Leave without visual route
              </button>
            )}
            <button
              className="button button-danger"
              type="button"
              onClick={() => {
                const element = pendingDelete;
                if (!element || !onDeleteVisualElement) return;
                void onDeleteVisualElement(element.id, {
                  leaveUnrouted: false,
                })
                  .then(() => setPendingDelete(null))
                  .catch(() => undefined);
              }}
            >
              {pendingDelete?.type === "switch"
                ? "Delete and reconnect"
                : "Delete element"}
            </button>
          </footer>
        </div>
      </Modal>
    </div>
  );
}

export function TopologyCanvas(props: TopologyCanvasProps) {
  return (
    <ReactFlowProvider>
      <TopologyCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
