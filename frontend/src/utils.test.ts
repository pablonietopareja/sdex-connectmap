import { describe, expect, it } from "vitest";
import { normalizeBaseUrl } from "./components/ConnectionForm";
import {
  calculateSummary,
  createRadialPositions,
  positionLayoutUpdate,
} from "./utils";
import { DEVICE_TYPES, makeNode } from "./test/fixtures";

describe("normalizeBaseUrl", () => {
  it("accepts HTTP(S), IPv6 and removes trailing slashes", () => {
    expect(normalizeBaseUrl(" https://sdex-suite:443/// ")).toBe(
      "https://sdex-suite",
    );
    expect(normalizeBaseUrl("http://[2001:db8::8]:1443/")).toBe(
      "http://[2001:db8::8]:1443",
    );
  });

  it.each([
    ["ftp://sdex-suite", "Only HTTP and HTTPS"],
    ["https://admin:secret@sdex-suite", "without embedded credentials"],
    ["https://sdex-suite/runtime", "without a path"],
    ["https://sdex-suite?debug=true", "Query strings"],
    ["https://sdex-suite#runtime", "Query strings"],
    ["http://sdex-suite:0", "port from 1 to 65535"],
    ["http://bad host:8080", "valid SDEX URL"],
    ["https://sdex-suite:99999", "valid SDEX URL"],
  ])("rejects unsafe or unsupported URL %s", (input, message) => {
    expect(() => normalizeBaseUrl(input)).toThrow(message);
  });
});

describe("topology utilities", () => {
  it("calculates status and per-type counts without merging OPC UA roles", () => {
    const nodes = [
      makeNode(),
      makeNode({
        id: "opcua:remote",
        type: "opcua_remote_server",
        status: "unknown",
      }),
      makeNode({
        id: "opcua:local",
        type: "opcua_local_endpoint",
        status: "disabled",
        enabled: false,
      }),
      makeNode({
        id: "fanuc:cnc",
        type: "fanuc_cnc",
        status: "disconnected",
      }),
      makeNode({
        id: "s7:line",
        type: "siemens_s7_1200_1500",
        status: "degraded",
      }),
    ];

    expect(calculateSummary(nodes)).toEqual({
      total_configured: 5,
      enabled: 4,
      connected: 1,
      disconnected: 1,
      disabled: 1,
      unknown_degraded: 2,
      by_type: {
        modbus: 1,
        opcua_remote_server: 1,
        opcua_local_endpoint: 1,
        fanuc_cnc: 1,
        siemens_s7_1200_1500: 1,
      },
    });
  });

  it("creates collision-free dynamic rings for forty nodes", () => {
    const nodes = Array.from({ length: 40 }, (_, index) =>
      makeNode({
        id: `node:${index.toString().padStart(2, "0")}`,
        display_name: `Node ${index}`,
        type: DEVICE_TYPES[index % DEVICE_TYPES.length],
      }),
    );
    const positions = createRadialPositions(nodes);
    const points = nodes.map((node) => positions[node.id]);

    expect(points.every(Boolean)).toBe(true);
    for (let index = 0; index < points.length; index += 1) {
      const point = points[index]!;
      for (let other = index + 1; other < points.length; other += 1) {
        const comparison = points[other]!;
        const overlaps =
          Math.abs(point.x - comparison.x) < 292 &&
          Math.abs(point.y - comparison.y) < 204;
        expect(overlaps).toBe(false);
      }
    }
    const radii = new Set(
      points.map((point) => Math.round(Math.hypot(point!.x, point!.y))),
    );
    expect(radii.size).toBeGreaterThan(2);
  });

  it("preserves manually placed nodes and finds a free slot for a new node", () => {
    const existing = { "modbus:line-1": { x: 420, y: 0 } };
    const newNode = makeNode({ id: "mqtt:new", type: "mqtt_broker" });
    const positions = createRadialPositions([makeNode(), newNode], existing);

    expect(positions["modbus:line-1"]).toEqual({ x: 420, y: 0 });
    expect(positions["mqtt:new"]).toBeDefined();
    expect(positions["mqtt:new"]).not.toEqual({ x: 420, y: 0 });
  });

  it("creates the persistence payload used at drag stop", () => {
    expect(positionLayoutUpdate("modbus:line-1", { x: 124, y: -36 })).toEqual({
      positions: [{ node_id: "modbus:line-1", x: 124, y: -36 }],
    });
  });
});
