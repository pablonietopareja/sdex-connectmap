import { describe, expect, it, vi } from "vitest";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  buildEdges,
  buildNodes,
  edgeIdForConnection,
  persistableVisualHandle,
  stableSwitchHandleId,
  visualLinkHandlesForCreate,
} from "./TopologyCanvas";
import { makeNode, makeSnapshot } from "../../test/fixtures";
import type { TopologyEdge } from "../../types";
import { createRadialPositions } from "../../utils";

describe("topology graph model", () => {
  const disabled = makeNode({
    id: "mqtt:disabled",
    type: "mqtt_broker",
    enabled: false,
    status: "disabled",
  });
  const disconnected = makeNode({
    id: "fanuc:cell-2",
    type: "fanuc_cnc",
    status: "disconnected",
  });
  const unknown = makeNode({
    id: "rockwell:line-3",
    type: "rockwell_allen_bradley",
    status: "unknown",
  });
  const snapshot = makeSnapshot([makeNode(), disabled, disconnected, unknown]);
  const positions = createRadialPositions(snapshot.nodes);

  it("locks SDEX and toggles drag only for external nodes", () => {
    const readOnly = buildNodes(snapshot, positions, false, true, vi.fn());
    const editable = buildNodes(snapshot, positions, true, true, vi.fn());

    expect(readOnly.find((node) => node.type === "gateway")?.draggable).toBe(false);
    expect(
      readOnly
        .filter((node) => node.type === "connection")
        .every((node) => node.draggable === false),
    ).toBe(true);
    expect(editable.find((node) => node.type === "gateway")?.draggable).toBe(false);
    expect(editable.every((node) => node.focusable === false)).toBe(true);
    expect(
      editable
        .filter((node) => node.type === "connection")
        .every((node) => node.draggable === true),
    ).toBe(true);
  });

  it("hides disabled cards by default and shows them in the explicit mode", () => {
    expect(buildNodes(snapshot, positions, false, false, vi.fn())).toHaveLength(4);
    expect(buildNodes(snapshot, positions, false, true, vi.fn())).toHaveLength(5);
  });

  it("never creates a cable for disabled connections", () => {
    const edges = buildEdges(snapshot, positions, true);
    expect(edges.some((edge) => edge.source === disabled.id)).toBe(false);
    expect(edges).toHaveLength(3);
  });

  it("keeps connected, disconnected, and unknown semantics distinct", () => {
    const edges = buildEdges(snapshot, positions, true);
    expect(edges.find((edge) => edge.source === "modbus:line-1")?.data?.status).toBe(
      "connected",
    );
    expect(edges.find((edge) => edge.source === disconnected.id)?.data?.status).toBe(
      "disconnected",
    );
    expect(edges.find((edge) => edge.source === unknown.id)?.data?.status).toBe(
      "unknown",
    );
  });

  it("builds stable semantic device-to-SDEX edges and routes by assignment", () => {
    const eth1Node = makeNode({
      id: "modbus:eth1",
      interface_assignment: {
        resolved: true,
        interface_name: "eth1",
        source: "subnet",
        reason: "eth1 subnet",
      },
    });
    const eth2Node = makeNode({
      id: "mqtt:eth2",
      type: "mqtt_broker",
      interface_assignment: {
        resolved: true,
        interface_name: "eth2",
        source: "explicit",
        reason: "reported by SDEX",
      },
    });
    const routed = makeSnapshot([eth1Node, eth2Node]);
    const edges = buildEdges(
      routed,
      {
        [eth1Node.id]: { x: -400, y: 0 },
        [eth2Node.id]: { x: 0, y: -400 },
      },
      false,
    );

    expect(edges).toHaveLength(2);
    expect(edges[0]).toMatchObject({
      id: edgeIdForConnection(eth1Node.id),
      source: eth1Node.id,
      target: routed.gateway.id,
      sourceHandle: "right",
      targetHandle: "sdex-eth1",
      focusable: true,
    });
    expect(edges[1]).toMatchObject({
      id: edgeIdForConnection(eth2Node.id),
      source: eth2Node.id,
      target: routed.gateway.id,
      sourceHandle: "bottom",
      targetHandle: "sdex-eth2",
    });
  });

  it("prefers canonical edges and never guesses a handle for unresolved data", () => {
    const resolved = makeNode({ id: "modbus:canonical" });
    const unresolved = makeNode({
      id: "mqtt:unresolved",
      type: "mqtt_broker",
    });
    const canonicalEdges: TopologyEdge[] = [
      {
        id: edgeIdForConnection(resolved.id),
        source: resolved.id,
        target: "sdex_gateway:sdex",
        source_handle: null,
        // A contradictory wire hint must not override the assignment.
        target_handle: "sdex-eth1",
        interface_assignment: {
          resolved: true,
          interface_name: "eth2",
          source: "manual_override",
          reason: "operator override",
        },
        style: null,
      },
      {
        id: edgeIdForConnection(unresolved.id),
        source: unresolved.id,
        target: "sdex_gateway:sdex",
        source_handle: null,
        target_handle: null,
        interface_assignment: {
          resolved: false,
          interface_name: null,
          source: "unresolved",
          reason: "No matching subnet.",
        },
        style: null,
      },
    ];
    const edges = buildEdges(
      makeSnapshot([resolved, unresolved], { edges: canonicalEdges }),
      {
        [resolved.id]: { x: 0, y: 400 },
        [unresolved.id]: { x: 400, y: 0 },
      },
      false,
    );

    expect(edges).toHaveLength(1);
    expect(edges[0]?.source).toBe(resolved.id);
    expect(edges[0]?.targetHandle).toBe("sdex-eth2");
    expect(edges.some((edge) => edge.source === unresolved.id)).toBe(false);
  });

  it("opens a focusable edge from Enter or Space", () => {
    const onConfigure = vi.fn();
    const edge = buildEdges(snapshot, positions, true, onConfigure)[0];
    const onKeyDown = edge?.domAttributes?.onKeyDown;
    const preventDefault = vi.fn();
    const stopPropagation = vi.fn();

    onKeyDown?.({
      key: "Enter",
      preventDefault,
      stopPropagation,
    } as unknown as ReactKeyboardEvent<SVGGElement>);
    onKeyDown?.({
      key: " ",
      preventDefault,
      stopPropagation,
    } as unknown as ReactKeyboardEvent<SVGGElement>);

    expect(onConfigure).toHaveBeenNthCalledWith(
      1,
      edgeIdForConnection("modbus:line-1"),
    );
    expect(onConfigure).toHaveBeenCalledTimes(2);
    expect(preventDefault).toHaveBeenCalledTimes(2);
    expect(stopPropagation).toHaveBeenCalledTimes(2);
  });

  it("keeps a refreshed custom style isolated to its stable edge", () => {
    const first = makeNode({ id: "modbus:styled" });
    const second = makeNode({ id: "mqtt:default", type: "mqtt_broker" });
    const edges: TopologyEdge[] = [first, second].map((node, index) => ({
      id: edgeIdForConnection(node.id),
      source: node.id,
      target: "sdex_gateway:sdex",
      source_handle: null,
      target_handle: "sdex-eth1",
      interface_assignment: {
        resolved: true,
        interface_name: "eth1",
        source: "subnet",
        reason: "test subnet",
      },
      style:
        index === 0
          ? {
              edge_id: edgeIdForConnection(node.id),
              sheath_color: "#123456",
              flow_color: "#ABCDEF",
              reverse_flow: true,
              updated_at: "2026-07-29T10:00:00Z",
              schema_version: 1,
            }
          : null,
    }));
    const refreshed = makeSnapshot([first, second], { edges });
    const firstBuild = buildEdges(refreshed, positions, false);
    const afterRefetch = buildEdges({ ...refreshed, generated_at: "later" }, positions, false);

    expect(firstBuild.find((edge) => edge.source === first.id)?.data?.style).toMatchObject(
      {
        sheath_color: "#123456",
        flow_color: "#ABCDEF",
        reverse_flow: true,
      },
    );
    expect(firstBuild.find((edge) => edge.source === second.id)?.data?.style).toBeNull();
    expect(afterRefetch.find((edge) => edge.source === first.id)?.data?.style).toEqual(
      firstBuild.find((edge) => edge.source === first.id)?.data?.style,
    );
  });

  it("renders Rack parents before embedded members and keeps one aggregate uplink", () => {
    const first = makeNode({ id: "rockwell:first", type: "rockwell_allen_bradley" });
    const second = makeNode({ id: "rockwell:second", type: "rockwell_allen_bradley" });
    const aggregate = {
      status: "connected" as const,
      total: 2,
      connected: 2,
      disconnected: 0,
      disabled: 0,
      unknown: 0,
      degraded: 0,
      missing: 0,
      animated: true,
    };
    const visualSnapshot = makeSnapshot([first, second], {
      visual_topology: {
        elements: [
          {
            id: "rack:line-1",
            type: "rack",
            name: "Production Line 1",
            description: null,
            position: { x: -500, y: -200 },
            width: 1062,
            height: 324,
            external_interface: "eth1",
            rows: 1,
            columns: 3,
            capacity: 3,
            collapsed: false,
            aggregate,
            schema_version: 1,
            created_at: "2026-07-31T10:00:00Z",
            updated_at: "2026-07-31T10:00:00Z",
          },
        ],
        rack_memberships: [first, second].map((connection, column) => ({
          rack_id: "rack:line-1",
          connection_id: connection.id,
          row: 0,
          column,
          missing: false,
          connection,
        })),
        links: [],
        routes: {},
        unrouted_connection_ids: [],
      },
      edges: [
        {
          id: "visual-link:rack-uplink",
          source: "rack:line-1",
          target: "sdex_gateway:sdex",
          source_handle: "rack-right",
          target_handle: "sdex-eth1",
          interface_assignment: {
            resolved: true,
            interface_name: "eth1",
            source: "explicit",
            reason: "Rack external interface",
          },
          style: null,
          kind: "aggregate",
          route: null,
          aggregate,
        },
      ],
    });

    const nodes = buildNodes(visualSnapshot, {}, true, true, vi.fn());
    const rackIndex = nodes.findIndex((node) => node.id === "rack:line-1");
    const memberNodes = nodes.filter(
      (node) => node.type === "connection" && node.parentId === "rack:line-1",
    );
    expect(rackIndex).toBeGreaterThanOrEqual(0);
    expect(memberNodes).toHaveLength(2);
    expect(memberNodes.every((node) => nodes.indexOf(node) > rackIndex)).toBe(true);
    expect(memberNodes.map((node) => node.data.variant)).toEqual([
      "embedded",
      "embedded",
    ]);

    const edges = buildEdges(visualSnapshot, {}, true);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({
      source: "rack:line-1",
      target: "sdex_gateway:sdex",
      sourceHandle: "rack-right",
      targetHandle: "sdex-eth1",
    });
    expect(edges[0]?.data?.aggregate?.total).toBe(2);
  });

  it("builds a local Switch with only stable lateral handles", () => {
    const visualSnapshot = makeSnapshot(undefined, {
      visual_topology: {
        elements: [
          {
            id: "switch:line-1",
            type: "switch",
            name: "Line switch",
            description: "Visual aggregator",
            position: { x: 420, y: 0 },
            width: 310,
            height: 210,
            external_interface: "eth2",
            icon: "/icons/Switch.svg",
            status_mode: "neutral",
            schema_version: 1,
            created_at: "2026-07-31T10:00:00Z",
            updated_at: "2026-07-31T10:00:00Z",
          },
        ],
        rack_memberships: [],
        links: [
          {
            id: "visual-link:one",
            source: "modbus:line-1",
            target: "switch:line-1",
            source_handle: "right",
            target_handle: "switch-left-one",
            external_interface: "eth2",
            schema_version: 1,
            created_at: "2026-07-31T10:00:00Z",
            updated_at: "2026-07-31T10:00:00Z",
          },
        ],
        routes: {},
        unrouted_connection_ids: [],
      },
    });
    const switchNode = buildNodes(
      visualSnapshot,
      {},
      true,
      true,
      vi.fn(),
    ).find((node) => node.id === "switch:line-1");

    expect(switchNode?.type).toBe("switch");
    if (switchNode?.type !== "switch") throw new Error("Switch node missing");
    expect(switchNode.data.handles.map((handle) => handle.side)).toEqual(
      expect.arrayContaining(["left", "right"]),
    );
    expect(
      switchNode.data.handles.every(
        (handle) => handle.side !== ("top" as never) && handle.side !== ("bottom" as never),
      ),
    ).toBe(true);
  });

  it("expands legacy Switch placeholders into one stable handle per link", () => {
    const first = makeNode({ id: "modbus:first" });
    const second = makeNode({ id: "modbus:second" });
    const linkIds = ["visual-link:one", "visual-link:two"];
    const links = [first, second].map((connection, index) => ({
      id: linkIds[index] as string,
      source: connection.id,
      target: "switch:legacy",
      source_handle: "right",
      target_handle: "left:new",
      external_interface: "eth1" as const,
      schema_version: 1,
      created_at: "2026-07-31T10:00:00Z",
      updated_at: "2026-07-31T10:00:00Z",
    }));
    const visualSnapshot = makeSnapshot([first, second], {
      visual_topology: {
        elements: [
          {
            id: "switch:legacy",
            type: "switch",
            name: "Legacy handles",
            description: null,
            position: { x: 400, y: 0 },
            width: 310,
            height: 228,
            external_interface: "eth1",
            icon: "/icons/Switch.svg",
            status_mode: "neutral",
            schema_version: 1,
            created_at: "2026-07-31T10:00:00Z",
            updated_at: "2026-07-31T10:00:00Z",
          },
        ],
        rack_memberships: [],
        links,
        routes: {},
        unrouted_connection_ids: [],
      },
      edges: links.map((link) => ({
        id: link.id,
        source: link.source,
        target: link.target,
        source_handle: link.source_handle,
        target_handle: link.target_handle,
        interface_assignment: {
          resolved: true,
          interface_name: "eth1",
          source: "explicit",
          reason: "Legacy visual link",
        },
        style: null,
        kind: "visual",
        route: null,
        aggregate: null,
      })),
    });

    const switchNode = buildNodes(
      visualSnapshot,
      { [first.id]: { x: 0, y: -100 }, [second.id]: { x: 0, y: 100 } },
      true,
      true,
      vi.fn(),
    ).find((node) => node.id === "switch:legacy");
    if (switchNode?.type !== "switch") throw new Error("Switch node missing");

    const persistedHandles = switchNode.data.handles.filter(
      (handle) => handle.id !== "left:new" && handle.id !== "right:new",
    );
    expect(persistedHandles.map((handle) => handle.id)).toEqual([
      "left:visual-link:one",
      "left:visual-link:two",
    ]);
    expect(persistedHandles.map((handle) => handle.side)).toEqual([
      "left",
      "left",
    ]);
    expect(buildEdges(visualSnapshot, {}, true).map((edge) => edge.targetHandle)).toEqual([
      "left:visual-link:one",
      "left:visual-link:two",
    ]);
  });

  it("preserves the selected Switch side for Loose-mode create payloads", () => {
    // Loose mode permits a Switch target on the right and a Switch source on
    // the left. The API needs that side to mint a link-specific handle.
    expect(
      visualLinkHandlesForCreate(
        { sourceHandle: "right", targetHandle: "right:new" },
        false,
      ),
    ).toEqual({ source_handle: "right", target_handle: "right:new" });
    expect(
      visualLinkHandlesForCreate(
        { sourceHandle: "left:new", targetHandle: "sdex-eth1" },
        false,
      ),
    ).toEqual({ source_handle: "left:new", target_handle: "sdex-eth1" });
    expect(
      visualLinkHandlesForCreate(
        { sourceHandle: "right:new", targetHandle: "left" },
        true,
      ),
    ).toEqual({ source_handle: "left", target_handle: "right:new" });
    expect(persistableVisualHandle("rack-right")).toBe("rack-right");
    expect(stableSwitchHandleId("right:new", "left", "visual-link:9")).toBe(
      "right:visual-link:9",
    );
    expect(stableSwitchHandleId("left:new", "right", "visual-link:10")).toBe(
      "left:visual-link:10",
    );
  });
});
