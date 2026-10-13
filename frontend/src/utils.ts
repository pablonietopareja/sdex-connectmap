import {
  CONNECTION_PRESENTATION,
  DEFAULT_VIEWPORT,
  GATEWAY_ID,
} from "./constants";
import type {
  ConnectionNode,
  ConnectionStatus,
  ConnectionType,
  LayoutUpdate,
  Point,
  TopologySnapshot,
  TopologySummary,
  Viewport,
} from "./types";

export function formatTimestamp(
  value?: string | null,
  fallback = "Not yet",
): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function displayAddress(node: ConnectionNode): string {
  if (node.address) return node.address;
  if (node.host && node.port) return `${node.host}:${node.port}`;
  if (node.host) return node.host;
  if (node.endpoint_url) return node.endpoint_url;
  return "Address unavailable";
}

export function safeStatus(value: unknown): ConnectionStatus {
  return [
    "connected",
    "disconnected",
    "disabled",
    "unlicensed",
    "degraded",
    "unknown",
  ].includes(String(value))
    ? (value as ConnectionStatus)
    : "unknown";
}

export function safeConnectionType(value: unknown): ConnectionType {
  return Object.hasOwn(CONNECTION_PRESENTATION, String(value))
    ? (value as ConnectionType)
    : "modbus";
}

export function calculateSummary(nodes: ConnectionNode[]): TopologySummary {
  const summary: TopologySummary = {
    total_configured: nodes.length,
    enabled: 0,
    connected: 0,
    disconnected: 0,
    disabled: 0,
    unknown_degraded: 0,
    by_type: {},
  };

  for (const node of nodes) {
    summary.by_type[node.type] = (summary.by_type[node.type] ?? 0) + 1;
    if (node.enabled) summary.enabled += 1;
    if (node.status === "connected") summary.connected += 1;
    else if (node.status === "disconnected") summary.disconnected += 1;
    else if (node.status === "disabled") summary.disabled += 1;
    else summary.unknown_degraded += 1;
  }
  return summary;
}

export const NODE_VISUAL_VERSION = 2;
const NODE_SLOT_WIDTH = 388;
const NODE_SLOT_HEIGHT = 264;
const RING_START_RADIUS = 520;
const RING_GAP = 380;
const MIN_ARC_DISTANCE = 404;

function circularDistance(a: number, b: number): number {
  const delta = Math.abs(a - b) % (Math.PI * 2);
  return Math.min(delta, Math.PI * 2 - delta);
}

function preferredAngle(type: ConnectionType): number {
  const group = CONNECTION_PRESENTATION[type].group;
  if (group === "service") return 0;
  if (group === "plc") return Math.PI;
  if (group === "cnc") return Math.PI * 0.72;
  if (group === "field") return -Math.PI * 0.72;
  return -Math.PI / 2;
}

function positionsOverlap(a: Point, b: Point): boolean {
  return (
    Math.abs(a.x - b.x) < NODE_SLOT_WIDTH &&
    Math.abs(a.y - b.y) < NODE_SLOT_HEIGHT
  );
}

interface RadialSlot {
  point: Point;
  angle: number;
  ring: number;
}

function radialSlots(minimum: number): RadialSlot[] {
  const slots: RadialSlot[] = [];
  let ring = 0;
  while (slots.length < Math.max(minimum * 5, 40)) {
    const radius = RING_START_RADIUS + ring * RING_GAP;
    const capacity = Math.max(
      8,
      Math.floor((Math.PI * 2 * radius) / MIN_ARC_DISTANCE),
    );
    for (let index = 0; index < capacity; index += 1) {
      const angle = -Math.PI + (index / capacity) * Math.PI * 2;
      slots.push({
        point: {
          x: Math.round(Math.cos(angle) * radius),
          y: Math.round(Math.sin(angle) * radius),
        },
        angle,
        ring,
      });
    }
    ring += 1;
  }
  return slots;
}

/**
 * Builds stable, multi-ring positions. Existing positions are treated as occupied
 * and never changed, so newly discovered connections only fill genuinely free
 * radial slots.
 */
export function createRadialPositions(
  nodes: ConnectionNode[],
  existing: Record<string, Point> = {},
): Record<string, Point> {
  const positions: Record<string, Point> = {
    ...existing,
    [GATEWAY_ID]: { x: 0, y: 0 },
  };
  const missing = nodes
    .filter((node) => existing[node.id] === undefined)
    .sort((a, b) => a.id.localeCompare(b.id));
  const slots = radialSlots(nodes.length + Object.keys(existing).length);
  const used = Object.values(existing);

  for (const node of missing) {
    const preferred = preferredAngle(node.type);
    const available = slots
      .filter(
        (slot) => !used.some((position) => positionsOverlap(slot.point, position)),
      )
      .sort((a, b) => {
        const scoreA = circularDistance(a.angle, preferred) * 100 + a.ring * 2;
        const scoreB = circularDistance(b.angle, preferred) * 100 + b.ring * 2;
        return scoreA - scoreB;
      });
    const selected = available[0];
    if (selected) {
      positions[node.id] = selected.point;
      used.push(selected.point);
    }
  }
  return positions;
}

export function withCompleteLayout(snapshot: TopologySnapshot): {
  positions: Record<string, Point>;
  viewport: Viewport;
} {
  const savedVisualVersion =
    (snapshot.layout as { visual_version?: number } | undefined)
      ?.visual_version ?? 1;
  // Preview data is intentionally reflowed once when the visual card geometry
  // changes. Production positions remain untouched until the operator resets.
  const existing =
    snapshot.mock_mode && savedVisualVersion < NODE_VISUAL_VERSION
      ? {}
      : (snapshot.layout?.positions ?? {});
  const generated = createRadialPositions(snapshot.nodes, existing);
  return {
    positions: { ...generated, [snapshot.gateway.id]: { x: 0, y: 0 } },
    viewport: snapshot.layout?.viewport ?? DEFAULT_VIEWPORT,
  };
}

export function positionLayoutUpdate(
  nodeId: string,
  position: Point,
): LayoutUpdate {
  return {
    positions: [{ node_id: nodeId, x: position.x, y: position.y }],
  };
}

export function nodeIcon(node: ConnectionNode): string {
  const expected = CONNECTION_PRESENTATION[node.type]?.icon;
  if (expected) return expected;
  if (node.icon) {
    return node.icon.startsWith("/") ? node.icon : `/icons/${node.icon}`;
  }
  return "/icons/Modbus.svg";
}
