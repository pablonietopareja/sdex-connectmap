import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  EdgeLabelRenderer,
  useReactFlow,
  useViewport,
  type EdgeProps,
  type XYPosition,
} from "@xyflow/react";
import type {
  EdgeRoute,
  EdgeRouteUpdate,
  EdgeWaypoint,
} from "../../types/visual-topology";
import type { DataCableFlowEdge } from "../canvas/types";
import { AlertIcon } from "../icons";
import { normalizeHexColor } from "./color";
import {
  buildCableGeometry,
  isEditableTextTarget,
  nearestInsertionIndex,
  normalizeRouteUpdate,
  renumberWaypoints,
  type CableGeometry,
  type CableInteractionSegment,
} from "./routing";

const LABELS = {
  disconnected: "Communication lost",
  unknown: "Status unavailable",
  degraded: "Connection degraded",
  unlicensed: "Not licensed",
} as const;

const DRAG_THRESHOLD_PX = 4;

interface EdgeColorProperties extends CSSProperties {
  "--edge-sheath-color"?: string;
  "--edge-flow-color"?: string;
}

export interface EdgeRouteEditorData {
  route?: EdgeRoute | null;
  editorEnabled?: boolean;
  onSaveRoute?: (
    edgeId: string,
    update: EdgeRouteUpdate,
  ) => Promise<EdgeRoute | void> | EdgeRoute | void;
  onResetRoute?: (edgeId: string) => Promise<void> | void;
  onSelectEdge?: (edgeId: string) => void;
  onCancelRouteEditing?: (edgeId: string) => void;
  onRouteError?: (edgeId: string, error: unknown) => void;
  /** Test seam and compatibility fallback for browsers without randomUUID. */
  createWaypointId?: () => string;
}

type CableData = NonNullable<DataCableFlowEdge["data"]> & EdgeRouteEditorData;

interface ActiveDrag {
  pointerId: number;
  startClient: XYPosition;
  before: EdgeRouteUpdate;
  waypointId: string | null;
  moved: boolean;
  insertionSegments: CableInteractionSegment[];
}

interface RouteControlsProps {
  geometry: CableGeometry;
  route: EdgeRouteUpdate;
  selectedWaypointId: string | null;
  saving: boolean;
  error: string | null;
  onSelectWaypoint: (waypointId: string) => void;
  onWaypointPointerDown: (
    event: ReactPointerEvent<Element>,
    waypointId: string,
  ) => void;
  onPointerMove: (event: ReactPointerEvent<Element>) => void;
  onPointerUp: (event: ReactPointerEvent<Element>) => void;
  onPointerCancel: (event: ReactPointerEvent<Element>) => void;
  onReset: () => void;
}

let fallbackWaypointSequence = 0;

function nextWaypointId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const values = new Uint32Array(4);
    globalThis.crypto.getRandomValues(values);
    return `waypoint-${Array.from(values, (value) => value.toString(16)).join("-")}`;
  }
  fallbackWaypointSequence += 1;
  return `waypoint-session-${fallbackWaypointSequence}`;
}

function cloneRoute(route: EdgeRouteUpdate): EdgeRouteUpdate {
  return {
    routing_mode: route.routing_mode,
    waypoints: route.waypoints.map((waypoint) => ({ ...waypoint })),
  };
}

function routeMatches(left: EdgeRouteUpdate, right: EdgeRouteUpdate): boolean {
  if (
    left.routing_mode !== right.routing_mode ||
    left.waypoints.length !== right.waypoints.length
  ) {
    return false;
  }
  return left.waypoints.every((waypoint, index) => {
    const candidate = right.waypoints[index];
    return (
      candidate?.id === waypoint.id &&
      candidate.x === waypoint.x &&
      candidate.y === waypoint.y &&
      candidate.kind === waypoint.kind &&
      candidate.order === waypoint.order
    );
  });
}

function withWaypointPosition(
  route: EdgeRouteUpdate,
  waypointId: string,
  position: XYPosition,
  orthogonal: boolean,
): EdgeRouteUpdate {
  const kind = orthogonal ? "corner" : "free";
  return {
    routing_mode: orthogonal ? "orthogonal" : "manual",
    waypoints: renumberWaypoints(
      route.waypoints.map((waypoint) => ({
        ...waypoint,
        ...(waypoint.id === waypointId ? position : {}),
        kind,
      })),
    ),
  };
}

function insertWaypoint(
  route: EdgeRouteUpdate,
  waypoint: EdgeWaypoint,
  insertionIndex: number,
): EdgeRouteUpdate {
  const waypoints = route.waypoints.map((candidate) => ({ ...candidate }));
  waypoints.splice(
    Math.max(0, Math.min(insertionIndex, waypoints.length)),
    0,
    waypoint,
  );
  return {
    routing_mode: waypoint.kind === "corner" ? "orthogonal" : "manual",
    waypoints: renumberWaypoints(
      waypoints.map((candidate) => ({
        ...candidate,
        kind: waypoint.kind,
      })),
    ),
  };
}

function RouteControls({
  geometry,
  route,
  selectedWaypointId,
  saving,
  error,
  onSelectWaypoint,
  onWaypointPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onReset,
}: RouteControlsProps) {
  const { zoom } = useViewport();
  const inverseZoom = 1 / Math.max(zoom, 0.05);

  return (
    <EdgeLabelRenderer>
      {route.waypoints.map((waypoint, index) => (
        <div
          key={waypoint.id}
          className="edge-waypoint-anchor"
          style={{ transform: `translate(${waypoint.x}px, ${waypoint.y}px)` }}
        >
          <button
            className={`edge-waypoint nodrag nopan nowheel${
              selectedWaypointId === waypoint.id ? " is-selected" : ""
            }`}
            style={{ transform: `translate(-50%, -50%) scale(${inverseZoom})` }}
            type="button"
            aria-label={`Cable waypoint ${index + 1} of ${route.waypoints.length}`}
            aria-pressed={selectedWaypointId === waypoint.id}
            title={"Drag waypoint. Hold Ctrl for a 90\u00b0 bend."}
            disabled={saving}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onSelectWaypoint(waypoint.id);
            }}
            onDoubleClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
            onPointerDown={(event) => onWaypointPointerDown(event, waypoint.id)}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerCancel}
          >
            <span aria-hidden="true" />
          </button>
        </div>
      ))}

      <div
        className="edge-route-toolbar-anchor"
        style={{
          transform: `translate(${geometry.labelX}px, ${geometry.labelY}px)`,
        }}
      >
        <div
          className="edge-route-toolbar nodrag nopan nowheel"
          style={{ transform: `translate(-50%, -100%) scale(${inverseZoom})` }}
          aria-label="Cable route editor"
        >
          <span title={"Drag the cable to add a waypoint. Hold Ctrl for a 90\u00b0 bend."}>
            {"Drag cable \u00b7 Ctrl = 90\u00b0"}
          </span>
          {route.waypoints.length > 0 && (
            <button
              type="button"
              disabled={saving}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onReset();
              }}
            >
              Reset route
            </button>
          )}
          {error && (
            <span className="edge-route-error" role="alert">
              {error}
            </span>
          )}
        </div>
      </div>
    </EdgeLabelRenderer>
  );
}

function DataCableEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  data,
}: EdgeProps<DataCableFlowEdge>) {
  const editorData: CableData | undefined = data;
  const flow = useReactFlow();
  const initialRoute = normalizeRouteUpdate(editorData?.route);
  const [draftRoute, setDraftRouteState] = useState<EdgeRouteUpdate>(initialRoute);
  const [selectedWaypointId, setSelectedWaypointId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [editorError, setEditorError] = useState<string | null>(null);
  const draftRouteRef = useRef(initialRoute);
  const activeDragRef = useRef<ActiveDrag | null>(null);
  const saveGenerationRef = useRef(0);
  const pendingRouteRef = useRef<EdgeRouteUpdate | null>(null);

  const setDraftRoute = useCallback((route: EdgeRouteUpdate) => {
    const normalized = normalizeRouteUpdate(route);
    draftRouteRef.current = normalized;
    setDraftRouteState(normalized);
  }, []);

  useEffect(() => {
    if (activeDragRef.current || saving) return;
    const incoming = normalizeRouteUpdate(editorData?.route);
    const pending = pendingRouteRef.current;
    if (pending && !routeMatches(incoming, pending)) return;
    pendingRouteRef.current = null;
    setDraftRoute(incoming);
  }, [editorData?.route, id, saving, setDraftRoute]);

  useEffect(() => {
    if (selected && editorData?.editorEnabled) return;
    activeDragRef.current = null;
    setSelectedWaypointId(null);
  }, [editorData?.editorEnabled, selected]);

  const geometry = useMemo(
    () =>
      buildCableGeometry({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
        route: draftRoute,
      }),
    [
      draftRoute,
      sourcePosition,
      sourceX,
      sourceY,
      targetPosition,
      targetX,
      targetY,
    ],
  );
  const geometryRef = useRef(geometry);
  geometryRef.current = geometry;

  const status = data?.status ?? "unknown";
  const flowAnimated =
    data?.stale !== true && (data?.flowAnimated ?? status === "connected");
  const stopped = !flowAnimated;
  const compactLabel = Math.hypot(targetX - sourceX, targetY - sourceY) < 260;
  const label =
    data?.stale
      ? "Snapshot unavailable"
      : status === "connected" || status === "disabled"
        ? null
        : LABELS[status];
  const sheathColor = normalizeHexColor(data?.style?.sheath_color ?? "");
  const flowColor = normalizeHexColor(data?.style?.flow_color ?? "");
  const reverseFlow = data?.style?.reverse_flow === true;
  const statusDescription =
    data?.stale
      ? "Snapshot unavailable"
      : status === "connected"
        ? reverseFlow
          ? "Connected reverse data flow"
          : "Connected data flow"
        : status === "disabled"
          ? "Connection disabled"
          : LABELS[status];
  const reason = data?.reason?.trim();
  const accessibleLabel = `${data?.connectionName?.trim() || "Data cable"}: ${statusDescription}${
    reason ? `. ${reason}` : ""
  }`;
  const colorProperties: EdgeColorProperties | undefined =
    sheathColor || flowColor
      ? {
          ...(sheathColor ? { "--edge-sheath-color": sheathColor } : {}),
          ...(flowColor ? { "--edge-flow-color": flowColor } : {}),
        }
      : undefined;
  const editorEnabled = editorData?.editorEnabled === true;
  const editable = editorEnabled && typeof editorData?.onSaveRoute === "function";

  const selectEdge = useCallback(() => {
    if (editorData?.onSelectEdge) {
      editorData.onSelectEdge(id);
      return;
    }
    flow.setNodes((nodes) =>
      nodes.map((node) => (node.selected ? { ...node, selected: false } : node)),
    );
    flow.setEdges((edges) =>
      edges.map((edge) => ({ ...edge, selected: edge.id === id })),
    );
  }, [editorData, flow, id]);

  const deselectEdge = useCallback(() => {
    if (editorData?.onCancelRouteEditing) {
      editorData.onCancelRouteEditing(id);
      return;
    }
    flow.setEdges((edges) =>
      edges.map((edge) =>
        edge.id === id && edge.selected ? { ...edge, selected: false } : edge,
      ),
    );
  }, [editorData, flow, id]);

  const persistRoute = useCallback(
    async (next: EdgeRouteUpdate, before: EdgeRouteUpdate): Promise<void> => {
      const callback = editorData?.onSaveRoute;
      if (!callback) return;
      const generation = saveGenerationRef.current + 1;
      saveGenerationRef.current = generation;
      pendingRouteRef.current = cloneRoute(next);
      setSaving(true);
      setEditorError(null);
      try {
        const saved = await callback(id, cloneRoute(next));
        if (generation !== saveGenerationRef.current) return;
        if (saved) {
          const normalized = normalizeRouteUpdate(saved);
          pendingRouteRef.current = normalized;
          setDraftRoute(normalized);
        }
      } catch (error) {
        if (generation !== saveGenerationRef.current) return;
        pendingRouteRef.current = null;
        setDraftRoute(before);
        setEditorError("The cable route could not be saved.");
        editorData?.onRouteError?.(id, error);
      } finally {
        if (generation === saveGenerationRef.current) setSaving(false);
      }
    },
    [editorData, id, setDraftRoute],
  );

  const resetRoute = useCallback(
    async (before = cloneRoute(draftRouteRef.current)): Promise<void> => {
      const next: EdgeRouteUpdate = { routing_mode: "auto", waypoints: [] };
      const generation = saveGenerationRef.current + 1;
      saveGenerationRef.current = generation;
      pendingRouteRef.current = next;
      setDraftRoute(next);
      setSelectedWaypointId(null);
      setSaving(true);
      setEditorError(null);
      try {
        if (editorData?.onResetRoute) {
          await editorData.onResetRoute(id);
        } else if (editorData?.onSaveRoute) {
          await editorData.onSaveRoute(id, next);
        }
      } catch (error) {
        if (generation !== saveGenerationRef.current) return;
        pendingRouteRef.current = null;
        setDraftRoute(before);
        setEditorError("The cable route could not be reset.");
        editorData?.onRouteError?.(id, error);
      } finally {
        if (generation === saveGenerationRef.current) setSaving(false);
      }
    },
    [editorData, id, setDraftRoute],
  );

  const uniqueWaypointId = useCallback(() => {
    const existing = new Set(draftRouteRef.current.waypoints.map(({ id: value }) => value));
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const candidate = editorData?.createWaypointId?.() ?? nextWaypointId();
      if (candidate && !existing.has(candidate)) return candidate;
    }
    return `${nextWaypointId()}-${draftRouteRef.current.waypoints.length}`;
  }, [editorData]);

  const pointFromEvent = useCallback(
    (event: ReactPointerEvent<Element>): XYPosition =>
      flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }),
    [flow],
  );

  const updateActiveDrag = useCallback(
    (event: ReactPointerEvent<Element>, force = false): void => {
      const active = activeDragRef.current;
      if (!active || active.pointerId !== event.pointerId) return;
      const distance = Math.hypot(
        event.clientX - active.startClient.x,
        event.clientY - active.startClient.y,
      );
      if (!force && !active.moved && distance < DRAG_THRESHOLD_PX) return;

      const position = pointFromEvent(event);
      let route = draftRouteRef.current;
      if (!active.waypointId) {
        const waypointId = uniqueWaypointId();
        const insertionIndex = nearestInsertionIndex(
          position,
          active.insertionSegments,
        );
        route = insertWaypoint(
          route,
          {
            id: waypointId,
            x: position.x,
            y: position.y,
            kind: event.ctrlKey ? "corner" : "free",
            order: insertionIndex,
          },
          insertionIndex,
        );
        active.waypointId = waypointId;
        setSelectedWaypointId(waypointId);
      }
      route = withWaypointPosition(
        route,
        active.waypointId,
        position,
        event.ctrlKey,
      );
      active.moved = true;
      setDraftRoute(route);
    },
    [pointFromEvent, setDraftRoute, uniqueWaypointId],
  );

  const beginCableDrag = useCallback(
    (event: ReactPointerEvent<Element>) => {
      if (!editable || event.button !== 0 || saving) return;
      event.preventDefault();
      event.stopPropagation();
      selectEdge();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      activeDragRef.current = {
        pointerId: event.pointerId,
        startClient: { x: event.clientX, y: event.clientY },
        before: cloneRoute(draftRouteRef.current),
        waypointId: null,
        moved: false,
        insertionSegments: geometryRef.current.interactionSegments.map((segment) => ({
          ...segment,
          start: { ...segment.start },
          end: { ...segment.end },
        })),
      };
      setEditorError(null);
    },
    [editable, saving, selectEdge],
  );

  const beginWaypointDrag = useCallback(
    (event: ReactPointerEvent<Element>, waypointId: string) => {
      if (!editable || event.button !== 0 || saving) return;
      event.preventDefault();
      event.stopPropagation();
      selectEdge();
      setSelectedWaypointId(waypointId);
      event.currentTarget.setPointerCapture?.(event.pointerId);
      activeDragRef.current = {
        pointerId: event.pointerId,
        startClient: { x: event.clientX, y: event.clientY },
        before: cloneRoute(draftRouteRef.current),
        waypointId,
        moved: false,
        insertionSegments: [],
      };
      setEditorError(null);
    },
    [editable, saving, selectEdge],
  );

  const finishDrag = useCallback(
    (event: ReactPointerEvent<Element>) => {
      const active = activeDragRef.current;
      if (!active || active.pointerId !== event.pointerId) return;
      event.preventDefault();
      event.stopPropagation();

      // Ctrl+click is the unambiguous keyboard-assisted way to add a corner.
      if (!active.moved && !active.waypointId && event.ctrlKey) {
        updateActiveDrag(event, true);
      } else if (active.moved && active.waypointId) {
        updateActiveDrag(event, true);
      }
      const completed = activeDragRef.current;
      activeDragRef.current = null;
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      if (completed?.moved) {
        void persistRoute(cloneRoute(draftRouteRef.current), completed.before);
      }
    },
    [persistRoute, updateActiveDrag],
  );

  const cancelDrag = useCallback(
    (event?: ReactPointerEvent<Element>) => {
      const active = activeDragRef.current;
      if (!active) return;
      if (event && active.pointerId !== event.pointerId) return;
      event?.preventDefault();
      event?.stopPropagation();
      event?.currentTarget.releasePointerCapture?.(active.pointerId);
      activeDragRef.current = null;
      setDraftRoute(active.before);
    },
    [setDraftRoute],
  );

  const deleteSelectedWaypoint = useCallback(() => {
    if (!selectedWaypointId || saving) return;
    const before = cloneRoute(draftRouteRef.current);
    const waypoints = renumberWaypoints(
      before.waypoints.filter((waypoint) => waypoint.id !== selectedWaypointId),
    );
    setSelectedWaypointId(null);
    if (waypoints.length === 0) {
      void resetRoute(before);
      return;
    }
    const next = { ...before, waypoints };
    setDraftRoute(next);
    void persistRoute(next, before);
  }, [persistRoute, resetRoute, saving, selectedWaypointId, setDraftRoute]);

  useEffect(() => {
    if (!selected || !editorEnabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTextTarget(event.target)) return;
      if (
        selectedWaypointId &&
        (event.key === "Delete" || event.key === "Backspace")
      ) {
        event.preventDefault();
        event.stopPropagation();
        deleteSelectedWaypoint();
        return;
      }
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      if (activeDragRef.current) {
        const active = activeDragRef.current;
        activeDragRef.current = null;
        setDraftRoute(active.before);
      }
      setSelectedWaypointId(null);
      deselectEdge();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [
    deleteSelectedWaypoint,
    deselectEdge,
    editorEnabled,
    selected,
    selectedWaypointId,
    setDraftRoute,
  ]);

  return (
    <>
      <g
        className={[
          "data-cable-edge",
          `edge-${status}`,
          data?.stale ? "edge-stale" : "",
          selected && editorEnabled ? "edge-route-selected" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        data-testid={`edge-${status}`}
        data-routing-mode={draftRoute.routing_mode}
        aria-label={accessibleLabel}
        data-flow-direction={reverseFlow ? "reverse" : "forward"}
        style={colorProperties}
      >
        <title>{accessibleLabel}</title>
        <path className="edge-hit-area" d={geometry.path} fill="none" />
        <path
          id={id}
          className="edge-cable-base"
          d={geometry.path}
          fill="none"
          pathLength={1}
          style={
            sheathColor ? { stroke: "var(--edge-sheath-color)" } : undefined
          }
        />
        {!stopped && (
          <path
            className={`edge-data-flow${
              reverseFlow ? " edge-data-flow-reverse" : ""
            }`}
            d={geometry.path}
            fill="none"
            pathLength={1}
            data-flow-direction={reverseFlow ? "reverse" : "forward"}
            style={{
              ...(flowColor ? { stroke: "var(--edge-flow-color)" } : {}),
              animationDirection: reverseFlow ? "reverse" : "normal",
            }}
          />
        )}
      </g>

      {editable && (
        <path
          className="edge-route-hit-area nodrag nopan"
          d={geometry.path}
          fill="none"
          data-testid={`edge-route-hit-${id}`}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            selectEdge();
          }}
          onDoubleClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            data?.onConfigure(id);
          }}
          onPointerDown={beginCableDrag}
          onPointerMove={updateActiveDrag}
          onPointerUp={finishDrag}
          onPointerCancel={cancelDrag}
        />
      )}

      {selected && editable && (
        <RouteControls
          geometry={geometry}
          route={draftRoute}
          selectedWaypointId={selectedWaypointId}
          saving={saving}
          error={editorError}
          onSelectWaypoint={setSelectedWaypointId}
          onWaypointPointerDown={beginWaypointDrag}
          onPointerMove={updateActiveDrag}
          onPointerUp={finishDrag}
          onPointerCancel={cancelDrag}
          onReset={() => void resetRoute()}
        />
      )}

      {label && (
        <EdgeLabelRenderer>
          <div
            className={[
              "edge-message",
              `edge-message-${status}`,
              compactLabel ? "edge-message-compact" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            style={{
              transform: `translate(-50%, -50%) translate(${geometry.labelX}px, ${geometry.labelY}px)`,
            }}
            title={data?.reason ?? label}
            role="status"
            aria-label={label}
            onDoubleClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              data?.onConfigure(id);
            }}
          >
            <AlertIcon />
            <span>{label}</span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const DataCableEdge = memo(DataCableEdgeComponent);
