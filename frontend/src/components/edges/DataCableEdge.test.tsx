import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { EdgeProps } from "@xyflow/react";
import type { ReactNode } from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { EdgeRoute, EdgeRouteUpdate } from "../../types/visual-topology";
import type { DataCableFlowEdge } from "../canvas/types";

const flowMocks = vi.hoisted(() => ({
  setNodes: vi.fn(),
  setEdges: vi.fn(),
}));

vi.mock("@xyflow/react", () => ({
  EdgeLabelRenderer: ({ children }: { children: ReactNode }) => <>{children}</>,
  Position: {
    Left: "left",
    Right: "right",
    Top: "top",
    Bottom: "bottom",
  },
  getBezierPath: ({
    sourceX,
    sourceY,
    targetX,
    targetY,
  }: {
    sourceX: number;
    sourceY: number;
    targetX: number;
    targetY: number;
  }) => [
    `M ${sourceX} ${sourceY} C 25 0 75 100 ${targetX} ${targetY}`,
    (sourceX + targetX) / 2,
    (sourceY + targetY) / 2,
  ],
  useReactFlow: () => ({
    screenToFlowPosition: ({ x, y }: { x: number; y: number }) => ({
      x: (x - 10) / 2,
      y: (y - 20) / 2,
    }),
    setNodes: flowMocks.setNodes,
    setEdges: flowMocks.setEdges,
  }),
  useViewport: () => ({ x: 0, y: 0, zoom: 1 }),
}));

import {
  DataCableEdge,
  type EdgeRouteEditorData,
} from "./DataCableEdge";

beforeAll(() => {
  class PointerEventMock extends MouseEvent {
    readonly pointerId: number;

    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
    }
  }
  Object.defineProperty(window, "PointerEvent", {
    configurable: true,
    value: PointerEventMock,
  });
});

const MANUAL_ROUTE: EdgeRoute = {
  edge_id: "edge-device",
  routing_mode: "manual",
  waypoints: [
    { id: "waypoint-a", x: 40, y: 50, kind: "free", order: 0 },
  ],
  schema_version: 1,
  updated_at: "2026-07-31T09:00:00Z",
};

type EditorCallbacks = Pick<
  EdgeRouteEditorData,
  | "onSaveRoute"
  | "onResetRoute"
  | "onSelectEdge"
  | "onCancelRouteEditing"
  | "onRouteError"
>;

function edgeProps(
  callbacks: EditorCallbacks = {},
  overrides: {
    selected?: boolean;
    editorEnabled?: boolean;
    route?: EdgeRoute | null;
  } = {},
): EdgeProps<DataCableFlowEdge> {
  return {
    id: "edge-device",
    source: "device",
    target: "sdex",
    sourceX: 0,
    sourceY: 0,
    targetX: 100,
    targetY: 100,
    sourcePosition: "right",
    targetPosition: "left",
    selected: overrides.selected ?? true,
    data: {
      status: "connected",
      stale: false,
      style: null,
      connectionName: "Test device",
      networkInterface: "eth1",
      onConfigure: vi.fn(),
      route: overrides.route === undefined ? MANUAL_ROUTE : overrides.route,
      editorEnabled: overrides.editorEnabled ?? true,
      createWaypointId: () => "created-waypoint",
      ...callbacks,
    },
  } as unknown as EdgeProps<DataCableFlowEdge>;
}

function renderEdge(props: EdgeProps<DataCableFlowEdge>) {
  return render(
    <div>
      <input aria-label="External editor input" />
      <svg>
        <DataCableEdge {...props} />
      </svg>
    </div>,
  );
}

describe("DataCableEdge route editing", () => {
  beforeEach(() => {
    flowMocks.setNodes.mockClear();
    flowMocks.setEdges.mockClear();
  });

  it("uses one exact path for hit testing, sheath, flow and editor layers", () => {
    const onSaveRoute = vi.fn();
    const { container, rerender } = renderEdge(edgeProps({ onSaveRoute }));
    const paths = Array.from(container.querySelectorAll("path[d]"));

    expect(paths).toHaveLength(4);
    expect(new Set(paths.map((path) => path.getAttribute("d"))).size).toBe(1);
    expect(screen.getByRole("button", { name: /Cable waypoint 1/ })).toBeVisible();

    rerender(
      <div>
        <input aria-label="External editor input" />
        <svg>
          <DataCableEdge {...edgeProps({ onSaveRoute }, { selected: false })} />
        </svg>
      </div>,
    );
    expect(screen.queryByRole("button", { name: /Cable waypoint/ })).toBeNull();
    expect(screen.getByTestId("edge-route-hit-edge-device")).toBeInTheDocument();

    rerender(
      <div>
        <input aria-label="External editor input" />
        <svg>
          <DataCableEdge
            {...edgeProps({ onSaveRoute }, { editorEnabled: false })}
          />
        </svg>
      </div>,
    );
    expect(screen.queryByTestId("edge-route-hit-edge-device")).toBeNull();
  });

  it("honors aggregate flow animation while stale data always stops it", () => {
    const props = edgeProps({ onSaveRoute: vi.fn() });
    if (props.data) {
      props.data.status = "degraded";
      props.data.flowAnimated = true;
    }
    const { container, rerender } = renderEdge(props);
    expect(container.querySelector(".edge-data-flow")).toBeInTheDocument();

    const staleProps = edgeProps({ onSaveRoute: vi.fn() });
    if (staleProps.data) {
      staleProps.data.status = "connected";
      staleProps.data.flowAnimated = true;
      staleProps.data.stale = true;
    }
    rerender(
      <div>
        <input aria-label="External editor input" />
        <svg>
          <DataCableEdge {...staleProps} />
        </svg>
      </div>,
    );
    expect(container.querySelector(".edge-data-flow")).toBeNull();
  });

  it("exposes connected aggregate counts in its SVG tooltip and accessible name", () => {
    const props = edgeProps({ onSaveRoute: vi.fn() });
    const reason =
      "3 connected, 0 disconnected, 1 unknown, 0 disabled";
    if (props.data) {
      props.data.reason = reason;
      props.data.aggregate = {
        status: "connected",
        total: 4,
        connected: 3,
        disconnected: 0,
        disabled: 0,
        unknown: 1,
        degraded: 0,
        missing: 0,
        animated: true,
      };
    }

    renderEdge(props);

    const cable = screen.getByTestId("edge-connected");
    const description = `Test device: Connected data flow. ${reason}`;
    expect(cable).toHaveAttribute("aria-label", description);
    expect(cable.querySelector("title")).toHaveTextContent(description);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("selects with one click and exposes an explicit route reset", async () => {
    const onSaveRoute = vi.fn();
    const onResetRoute = vi.fn();
    renderEdge(edgeProps({ onSaveRoute, onResetRoute }));

    fireEvent.click(screen.getByTestId("edge-route-hit-edge-device"));
    expect(flowMocks.setEdges).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Reset route" }));
    await waitFor(() => expect(onResetRoute).toHaveBeenCalledWith("edge-device"));
    expect(onSaveRoute).not.toHaveBeenCalled();
  });

  it("creates a 90-degree corner with Ctrl and persists only on pointer-up", async () => {
    const onSaveRoute = vi.fn();
    renderEdge(edgeProps({ onSaveRoute }, { route: null }));
    const hitArea = screen.getByTestId("edge-route-hit-edge-device");

    fireEvent.pointerDown(hitArea, {
      button: 0,
      pointerId: 7,
      clientX: 110,
      clientY: 120,
      ctrlKey: true,
    });
    expect(onSaveRoute).not.toHaveBeenCalled();
    fireEvent.pointerUp(hitArea, {
      button: 0,
      pointerId: 7,
      clientX: 110,
      clientY: 120,
      ctrlKey: true,
    });

    await waitFor(() => expect(onSaveRoute).toHaveBeenCalledTimes(1));
    expect(onSaveRoute).toHaveBeenCalledWith("edge-device", {
      routing_mode: "orthogonal",
      waypoints: [
        {
          id: "created-waypoint",
          x: 50,
          y: 50,
          kind: "corner",
          order: 0,
        },
      ],
    });
  });

  it("previews waypoint movement locally and saves the final position once", async () => {
    const onSaveRoute = vi.fn();
    const { container } = renderEdge(edgeProps({ onSaveRoute }));
    const waypoint = screen.getByRole("button", { name: /Cable waypoint 1/ });
    const initialPath = container.querySelector(".edge-cable-base")?.getAttribute("d");

    fireEvent.pointerDown(waypoint, {
      button: 0,
      pointerId: 8,
      clientX: 90,
      clientY: 120,
    });
    fireEvent.pointerMove(waypoint, {
      pointerId: 8,
      clientX: 130,
      clientY: 140,
    });
    fireEvent.pointerMove(waypoint, {
      pointerId: 8,
      clientX: 150,
      clientY: 160,
    });

    expect(onSaveRoute).not.toHaveBeenCalled();
    const previewPaths = Array.from(container.querySelectorAll("path[d]"));
    expect(new Set(previewPaths.map((path) => path.getAttribute("d"))).size).toBe(1);
    expect(previewPaths[0]?.getAttribute("d")).not.toBe(initialPath);

    fireEvent.pointerUp(waypoint, {
      pointerId: 8,
      clientX: 170,
      clientY: 180,
    });

    await waitFor(() => expect(onSaveRoute).toHaveBeenCalledTimes(1));
    const update = onSaveRoute.mock.calls[0]?.[1] as EdgeRouteUpdate;
    expect(update.routing_mode).toBe("manual");
    expect(update.waypoints[0]).toMatchObject({ x: 80, y: 80, kind: "free" });
  });

  it("ignores Delete in text input and resets when the last waypoint is deleted", async () => {
    const onSaveRoute = vi.fn();
    const onResetRoute = vi.fn();
    renderEdge(edgeProps({ onSaveRoute, onResetRoute }));
    fireEvent.click(screen.getByRole("button", { name: /Cable waypoint 1/ }));

    fireEvent.keyDown(screen.getByRole("textbox", { name: "External editor input" }), {
      key: "Delete",
    });
    expect(onResetRoute).not.toHaveBeenCalled();

    fireEvent.keyDown(document.body, { key: "Delete" });
    await waitFor(() => expect(onResetRoute).toHaveBeenCalledWith("edge-device"));
    expect(onSaveRoute).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Cable waypoint/ })).toBeNull();
  });

  it("cancels an active preview with Escape without persisting", () => {
    const onSaveRoute = vi.fn();
    const onCancelRouteEditing = vi.fn();
    const { container } = renderEdge(
      edgeProps({ onSaveRoute, onCancelRouteEditing }),
    );
    const waypoint = screen.getByRole("button", { name: /Cable waypoint 1/ });
    const initialPath = container.querySelector(".edge-cable-base")?.getAttribute("d");

    fireEvent.pointerDown(waypoint, {
      button: 0,
      pointerId: 9,
      clientX: 90,
      clientY: 120,
    });
    fireEvent.pointerMove(waypoint, {
      pointerId: 9,
      clientX: 150,
      clientY: 160,
    });
    expect(container.querySelector(".edge-cable-base")?.getAttribute("d")).not.toBe(
      initialPath,
    );

    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onSaveRoute).not.toHaveBeenCalled();
    expect(onCancelRouteEditing).toHaveBeenCalledWith("edge-device");
    expect(container.querySelector(".edge-cable-base")?.getAttribute("d")).toBe(
      initialPath,
    );
  });

  it("keeps double-click configuration and rolls back a rejected save", async () => {
    const onConfigure = vi.fn();
    const onRouteError = vi.fn();
    const onSaveRoute = vi.fn().mockRejectedValue(new Error("offline"));
    const props = edgeProps({ onSaveRoute, onRouteError });
    if (props.data) props.data.onConfigure = onConfigure;
    const { container } = renderEdge(props);
    const hitArea = screen.getByTestId("edge-route-hit-edge-device");
    const initialPath = container.querySelector(".edge-cable-base")?.getAttribute("d");

    fireEvent.doubleClick(hitArea);
    expect(onConfigure).toHaveBeenCalledWith("edge-device");

    const waypoint = screen.getByRole("button", { name: /Cable waypoint 1/ });
    fireEvent.pointerDown(waypoint, {
      button: 0,
      pointerId: 10,
      clientX: 90,
      clientY: 120,
    });
    fireEvent.pointerMove(waypoint, {
      pointerId: 10,
      clientX: 150,
      clientY: 160,
    });
    fireEvent.pointerUp(waypoint, {
      pointerId: 10,
      clientX: 150,
      clientY: 160,
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The cable route could not be saved.",
    );
    expect(onRouteError).toHaveBeenCalledWith("edge-device", expect.any(Error));
    expect(container.querySelector(".edge-cable-base")?.getAttribute("d")).toBe(
      initialPath,
    );
  });
});
