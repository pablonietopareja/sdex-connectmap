import {
  Position,
  getBezierPath,
  type XYPosition,
} from "@xyflow/react";
import type {
  EdgeRoute,
  EdgeRouteUpdate,
  EdgeWaypoint,
  RoutingMode,
} from "../../types/visual-topology";

const SPLINE_SAMPLES_PER_SEGMENT = 12;
const ORTHOGONAL_DETOUR = 24;

type Axis = "horizontal" | "vertical";

export interface CableInteractionSegment {
  start: XYPosition;
  end: XYPosition;
  /** Index in the ordered waypoint array at which a new waypoint is inserted. */
  insertionIndex: number;
}

export interface CableGeometry {
  path: string;
  labelX: number;
  labelY: number;
  /** Source, user waypoints, target. Generated orthogonal elbows are excluded. */
  logicalPoints: XYPosition[];
  /** A lightweight approximation used only to choose where a new waypoint belongs. */
  interactionSegments: CableInteractionSegment[];
}

export interface CableGeometryParams {
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  sourcePosition: Position;
  targetPosition: Position;
  route?: EdgeRoute | EdgeRouteUpdate | null;
}

interface OrthogonalExpansion {
  points: XYPosition[];
  segments: CableInteractionSegment[];
}

function cleanNumber(value: number): number {
  if (Object.is(value, -0)) return 0;
  return Math.round(value * 1000) / 1000;
}

function coordinate(value: number): string {
  return String(cleanNumber(value));
}

function samePoint(left: XYPosition, right: XYPosition): boolean {
  return left.x === right.x && left.y === right.y;
}

function clonePoint(point: XYPosition): XYPosition {
  return { x: point.x, y: point.y };
}

function opposite(axis: Axis): Axis {
  return axis === "horizontal" ? "vertical" : "horizontal";
}

function axisForPosition(position: Position): Axis {
  return position === Position.Left || position === Position.Right
    ? "horizontal"
    : "vertical";
}

function detourSign(delta: number): number {
  return delta < 0 ? -1 : 1;
}

/**
 * Connects two points with an axis-aligned path that leaves and enters on the
 * requested axes. Degenerate aligned cases receive a small deterministic
 * dogleg so Ctrl routing never silently turns back into a diagonal/straight
 * segment with the wrong handle direction.
 */
function connectOrthogonally(
  start: XYPosition,
  end: XYPosition,
  startAxis: Axis,
  endAxis: Axis,
): XYPosition[] {
  const dx = end.x - start.x;
  const dy = end.y - start.y;

  if (samePoint(start, end)) return [clonePoint(end)];

  if (startAxis === endAxis) {
    if (startAxis === "horizontal") {
      const middleX =
        dx === 0
          ? start.x + ORTHOGONAL_DETOUR * detourSign(dy)
          : start.x + dx / 2;
      return [
        { x: middleX, y: start.y },
        { x: middleX, y: end.y },
        clonePoint(end),
      ];
    }
    const middleY =
      dy === 0
        ? start.y + ORTHOGONAL_DETOUR * detourSign(dx)
        : start.y + dy / 2;
    return [
      { x: start.x, y: middleY },
      { x: end.x, y: middleY },
      clonePoint(end),
    ];
  }

  if (startAxis === "horizontal") {
    if (dx !== 0 && dy !== 0) {
      return [{ x: end.x, y: start.y }, clonePoint(end)];
    }
    const elbowX =
      dx === 0
        ? start.x + ORTHOGONAL_DETOUR * detourSign(dy)
        : end.x;
    const elbowY =
      dy === 0
        ? start.y + ORTHOGONAL_DETOUR * detourSign(dx)
        : end.y;
    return [
      { x: elbowX, y: start.y },
      { x: elbowX, y: elbowY },
      { x: end.x, y: elbowY },
      clonePoint(end),
    ];
  }

  if (dx !== 0 && dy !== 0) {
    return [{ x: start.x, y: end.y }, clonePoint(end)];
  }
  const elbowY =
    dy === 0
      ? start.y + ORTHOGONAL_DETOUR * detourSign(dx)
      : end.y;
  const elbowX =
    dx === 0
      ? start.x + ORTHOGONAL_DETOUR * detourSign(dy)
      : end.x;
  return [
    { x: start.x, y: elbowY },
    { x: elbowX, y: elbowY },
    { x: elbowX, y: end.y },
    clonePoint(end),
  ];
}

function pushOrthogonalLeg(
  expansion: OrthogonalExpansion,
  next: XYPosition[],
  insertionIndex: number,
): void {
  for (const point of next) {
    const previous = expansion.points.at(-1);
    if (!previous || samePoint(previous, point)) continue;
    const normalized = {
      x: cleanNumber(point.x),
      y: cleanNumber(point.y),
    };
    expansion.segments.push({
      start: clonePoint(previous),
      end: clonePoint(normalized),
      insertionIndex,
    });
    expansion.points.push(normalized);
  }
}

/** Expands user pivots into a deterministic Manhattan route. */
export function expandOrthogonalRoute(
  logicalPoints: XYPosition[],
  sourcePosition: Position,
  targetPosition: Position,
): OrthogonalExpansion {
  const first = logicalPoints[0] ?? { x: 0, y: 0 };
  const expansion: OrthogonalExpansion = {
    points: [clonePoint(first)],
    segments: [],
  };
  if (logicalPoints.length < 2) return expansion;

  const departureAxis = axisForPosition(sourcePosition);
  let current = first;

  // Each user waypoint is a real pivot. It is entered on the perpendicular
  // axis and left on the departure axis, which guarantees a visible 90° turn
  // exactly at the point under the cursor.
  for (let index = 1; index < logicalPoints.length - 1; index += 1) {
    const waypoint = logicalPoints[index];
    if (!waypoint) continue;
    pushOrthogonalLeg(
      expansion,
      connectOrthogonally(
        current,
        waypoint,
        departureAxis,
        opposite(departureAxis),
      ),
      index - 1,
    );
    current = waypoint;
  }

  const target = logicalPoints.at(-1);
  if (target) {
    pushOrthogonalLeg(
      expansion,
      connectOrthogonally(
        current,
        target,
        departureAxis,
        axisForPosition(targetPosition),
      ),
      Math.max(0, logicalPoints.length - 2),
    );
  }
  return expansion;
}

function polylinePath(points: XYPosition[]): string {
  const first = points[0];
  if (!first) return "M 0 0";
  return [
    `M ${coordinate(first.x)} ${coordinate(first.y)}`,
    ...points.slice(1).map((point) => `L ${coordinate(point.x)} ${coordinate(point.y)}`),
  ].join(" ");
}

function cubicPoint(
  start: XYPosition,
  controlOne: XYPosition,
  controlTwo: XYPosition,
  end: XYPosition,
  t: number,
): XYPosition {
  const inverse = 1 - t;
  return {
    x:
      inverse ** 3 * start.x +
      3 * inverse ** 2 * t * controlOne.x +
      3 * inverse * t ** 2 * controlTwo.x +
      t ** 3 * end.x,
    y:
      inverse ** 3 * start.y +
      3 * inverse ** 2 * t * controlOne.y +
      3 * inverse * t ** 2 * controlTwo.y +
      t ** 3 * end.y,
  };
}

function manualSpline(logicalPoints: XYPosition[]): {
  path: string;
  sampledPoints: XYPosition[];
  segments: CableInteractionSegment[];
} {
  const first = logicalPoints[0] ?? { x: 0, y: 0 };
  if (logicalPoints.length < 2) {
    return { path: `M ${coordinate(first.x)} ${coordinate(first.y)}`, sampledPoints: [first], segments: [] };
  }

  const commands = [`M ${coordinate(first.x)} ${coordinate(first.y)}`];
  const sampledPoints = [clonePoint(first)];
  const segments: CableInteractionSegment[] = [];

  for (let index = 0; index < logicalPoints.length - 1; index += 1) {
    const before = logicalPoints[index - 1] ?? logicalPoints[index];
    const start = logicalPoints[index];
    const end = logicalPoints[index + 1];
    const after = logicalPoints[index + 2] ?? end;
    if (!before || !start || !end || !after) continue;

    // Cardinal/Catmull-Rom conversion: the curve interpolates every user
    // waypoint, so a visible handle always lies exactly on the cable.
    const controlOne = {
      x: start.x + (end.x - before.x) / 6,
      y: start.y + (end.y - before.y) / 6,
    };
    const controlTwo = {
      x: end.x - (after.x - start.x) / 6,
      y: end.y - (after.y - start.y) / 6,
    };
    commands.push(
      `C ${coordinate(controlOne.x)} ${coordinate(controlOne.y)} ` +
        `${coordinate(controlTwo.x)} ${coordinate(controlTwo.y)} ` +
        `${coordinate(end.x)} ${coordinate(end.y)}`,
    );

    let sampleStart = sampledPoints.at(-1) ?? start;
    for (let sample = 1; sample <= SPLINE_SAMPLES_PER_SEGMENT; sample += 1) {
      const point = cubicPoint(
        start,
        controlOne,
        controlTwo,
        end,
        sample / SPLINE_SAMPLES_PER_SEGMENT,
      );
      segments.push({
        start: clonePoint(sampleStart),
        end: clonePoint(point),
        insertionIndex: index,
      });
      sampledPoints.push(point);
      sampleStart = point;
    }
  }

  return { path: commands.join(" "), sampledPoints, segments };
}

function pointAtHalfLength(points: XYPosition[]): XYPosition {
  if (points.length === 0) return { x: 0, y: 0 };
  if (points.length === 1) return clonePoint(points[0] as XYPosition);

  const lengths: number[] = [];
  let total = 0;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const point = points[index];
    if (!previous || !point) continue;
    const length = Math.hypot(point.x - previous.x, point.y - previous.y);
    lengths.push(length);
    total += length;
  }
  if (total === 0) return clonePoint(points[0] as XYPosition);

  const target = total / 2;
  let traversed = 0;
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index] ?? 0;
    if (traversed + length >= target) {
      const start = points[index];
      const end = points[index + 1];
      if (!start || !end || length === 0) break;
      const ratio = (target - traversed) / length;
      return {
        x: start.x + (end.x - start.x) * ratio,
        y: start.y + (end.y - start.y) * ratio,
      };
    }
    traversed += length;
  }
  return clonePoint(points.at(-1) as XYPosition);
}

export function renumberWaypoints(waypoints: EdgeWaypoint[]): EdgeWaypoint[] {
  return waypoints.map((waypoint, order) => ({ ...waypoint, order }));
}

export function orderedWaypoints(
  route?: EdgeRoute | EdgeRouteUpdate | null,
): EdgeWaypoint[] {
  if (!route || route.routing_mode === "auto") return [];
  return renumberWaypoints(
    route.waypoints
      .filter(
        (waypoint) =>
          Number.isFinite(waypoint.x) && Number.isFinite(waypoint.y),
      )
      .map((waypoint) => ({ ...waypoint }))
      .sort((left, right) => left.order - right.order || left.id.localeCompare(right.id)),
  );
}

export function normalizeRouteUpdate(
  route?: EdgeRoute | EdgeRouteUpdate | null,
): EdgeRouteUpdate {
  const routingMode: RoutingMode = route?.routing_mode ?? "auto";
  return {
    routing_mode: routingMode,
    waypoints: routingMode === "auto" ? [] : orderedWaypoints(route),
  };
}

export function buildCableGeometry({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  route,
}: CableGeometryParams): CableGeometry {
  const normalized = normalizeRouteUpdate(route);
  const source = { x: sourceX, y: sourceY };
  const target = { x: targetX, y: targetY };
  const logicalPoints = [
    source,
    ...normalized.waypoints.map(({ x, y }) => ({ x, y })),
    target,
  ];

  if (normalized.routing_mode === "auto" || normalized.waypoints.length === 0) {
    const [path, labelX, labelY] = getBezierPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition,
      targetPosition,
      curvature: 0.32,
    });
    return {
      path,
      labelX,
      labelY,
      logicalPoints,
      interactionSegments: [
        { start: source, end: target, insertionIndex: 0 },
      ],
    };
  }

  if (normalized.routing_mode === "orthogonal") {
    const expansion = expandOrthogonalRoute(
      logicalPoints,
      sourcePosition,
      targetPosition,
    );
    const label = pointAtHalfLength(expansion.points);
    return {
      path: polylinePath(expansion.points),
      labelX: label.x,
      labelY: label.y,
      logicalPoints,
      interactionSegments: expansion.segments,
    };
  }

  const spline = manualSpline(logicalPoints);
  const label = pointAtHalfLength(spline.sampledPoints);
  return {
    path: spline.path,
    labelX: label.x,
    labelY: label.y,
    logicalPoints,
    interactionSegments: spline.segments,
  };
}

function squaredDistanceToSegment(
  point: XYPosition,
  start: XYPosition,
  end: XYPosition,
): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (dx === 0 && dy === 0) {
    return (point.x - start.x) ** 2 + (point.y - start.y) ** 2;
  }
  const projection = Math.max(
    0,
    Math.min(
      1,
      ((point.x - start.x) * dx + (point.y - start.y) * dy) /
        (dx * dx + dy * dy),
    ),
  );
  const projectedX = start.x + projection * dx;
  const projectedY = start.y + projection * dy;
  return (point.x - projectedX) ** 2 + (point.y - projectedY) ** 2;
}

export function nearestInsertionIndex(
  point: XYPosition,
  segments: CableInteractionSegment[],
): number {
  let selectedIndex = 0;
  let selectedDistance = Number.POSITIVE_INFINITY;
  for (const segment of segments) {
    const distance = squaredDistanceToSegment(point, segment.start, segment.end);
    if (
      distance < selectedDistance ||
      (distance === selectedDistance && segment.insertionIndex < selectedIndex)
    ) {
      selectedDistance = distance;
      selectedIndex = segment.insertionIndex;
    }
  }
  return selectedIndex;
}

export function isEditableTextTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest("input, textarea, select, [contenteditable='true']")) return true;
  const editableAncestor = target.closest("[contenteditable]");
  if (
    editableAncestor &&
    editableAncestor.getAttribute("contenteditable")?.toLowerCase() !== "false"
  ) {
    return true;
  }
  return target instanceof HTMLElement && target.isContentEditable === true;
}
