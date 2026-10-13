import { Position, getBezierPath } from "@xyflow/react";
import { describe, expect, it } from "vitest";
import type { EdgeRouteUpdate } from "../../types/visual-topology";
import {
  buildCableGeometry,
  expandOrthogonalRoute,
  isEditableTextTarget,
  nearestInsertionIndex,
  normalizeRouteUpdate,
} from "./routing";

const BASE_GEOMETRY = {
  sourceX: 0,
  sourceY: 0,
  targetX: 100,
  targetY: 80,
  sourcePosition: Position.Right,
  targetPosition: Position.Left,
};

function pathPoints(path: string): Array<{ x: number; y: number }> {
  return Array.from(path.matchAll(/[ML]\s+(-?[\d.]+)\s+(-?[\d.]+)/g), (match) => ({
    x: Number(match[1]),
    y: Number(match[2]),
  }));
}

describe("cable routing geometry", () => {
  it("preserves React Flow's bezier geometry in auto mode", () => {
    const expected = getBezierPath({ ...BASE_GEOMETRY, curvature: 0.32 });
    const geometry = buildCableGeometry({
      ...BASE_GEOMETRY,
      route: { routing_mode: "auto", waypoints: [] },
    });

    expect(geometry.path).toBe(expected[0]);
    expect([geometry.labelX, geometry.labelY]).toEqual(expected.slice(1, 3));
    expect(geometry.logicalPoints).toEqual([
      { x: 0, y: 0 },
      { x: 100, y: 80 },
    ]);
  });

  it("builds an interpolating manual spline through ordered waypoints", () => {
    const route: EdgeRouteUpdate = {
      routing_mode: "manual",
      waypoints: [
        { id: "second", x: 70, y: 20, kind: "free", order: 1 },
        { id: "first", x: 30, y: 60, kind: "free", order: 0 },
      ],
    };
    const geometry = buildCableGeometry({ ...BASE_GEOMETRY, route });

    expect(geometry.path).toMatch(/^M 0 0 C /);
    expect(geometry.path).toContain("30 60 C");
    expect(geometry.path).toContain("70 20 C");
    expect(geometry.path).toMatch(/100 80$/);
    expect(geometry.logicalPoints.slice(1, -1)).toEqual([
      { x: 30, y: 60 },
      { x: 70, y: 20 },
    ]);
    expect(Number.isFinite(geometry.labelX)).toBe(true);
    expect(Number.isFinite(geometry.labelY)).toBe(true);
  });

  it("expands corners into a deterministic axis-aligned route", () => {
    const logicalPoints = [
      { x: 0, y: 0 },
      { x: 50, y: 40 },
      { x: 100, y: 80 },
    ];
    const first = expandOrthogonalRoute(
      logicalPoints,
      Position.Right,
      Position.Left,
    );
    const second = expandOrthogonalRoute(
      logicalPoints,
      Position.Right,
      Position.Left,
    );
    const geometry = buildCableGeometry({
      ...BASE_GEOMETRY,
      route: {
        routing_mode: "orthogonal",
        waypoints: [
          { id: "corner", x: 50, y: 40, kind: "corner", order: 0 },
        ],
      },
    });
    const points = pathPoints(geometry.path);

    expect(first).toEqual(second);
    expect(points).toContainEqual({ x: 50, y: 40 });
    expect(points[0]).toEqual({ x: 0, y: 0 });
    expect(points.at(-1)).toEqual({ x: 100, y: 80 });
    for (let index = 1; index < points.length; index += 1) {
      const previous = points[index - 1];
      const point = points[index];
      expect(previous?.x === point?.x || previous?.y === point?.y).toBe(true);
    }
  });

  it("selects the insertion slot nearest to the pointer", () => {
    const segments = [
      {
        start: { x: 0, y: 0 },
        end: { x: 50, y: 0 },
        insertionIndex: 0,
      },
      {
        start: { x: 50, y: 0 },
        end: { x: 100, y: 0 },
        insertionIndex: 1,
      },
    ];

    expect(nearestInsertionIndex({ x: 12, y: 3 }, segments)).toBe(0);
    expect(nearestInsertionIndex({ x: 92, y: 3 }, segments)).toBe(1);
  });

  it("normalizes order and discards invalid coordinates", () => {
    const route = normalizeRouteUpdate({
      routing_mode: "manual",
      waypoints: [
        { id: "late", x: 20, y: 20, kind: "free", order: 5 },
        { id: "invalid", x: Number.NaN, y: 10, kind: "free", order: 1 },
        { id: "early", x: 10, y: 10, kind: "free", order: -1 },
      ],
    });

    expect(route.waypoints.map(({ id, order }) => ({ id, order }))).toEqual([
      { id: "early", order: 0 },
      { id: "late", order: 1 },
    ]);
    expect(
      normalizeRouteUpdate({
        routing_mode: "auto",
        waypoints: route.waypoints,
      }).waypoints,
    ).toEqual([]);
  });
});

describe("route editor keyboard target detection", () => {
  it("protects text controls and contenteditable regions", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const editable = document.createElement("div");
    const child = document.createElement("span");
    editable.setAttribute("contenteditable", "true");
    editable.append(child);

    expect(isEditableTextTarget(input)).toBe(true);
    expect(isEditableTextTarget(textarea)).toBe(true);
    expect(isEditableTextTarget(child)).toBe(true);
    expect(isEditableTextTarget(document.createElement("button"))).toBe(false);
  });
});
