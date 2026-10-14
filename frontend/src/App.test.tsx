import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeSnapshot } from "./test/fixtures";
import type { ConnectionNode, TopologyEvent, TopologySnapshot, VisualElement } from "./types";

const apiMocks = vi.hoisted(() => ({
  getConfigStatus: vi.fn(),
  getTopology: vi.fn(),
  getSettings: vi.fn(),
  refreshTopology: vi.fn(),
  testConfig: vi.fn(),
  saveConfig: vi.fn(),
  updateSettings: vi.fn(),
  saveLayout: vi.fn(),
  resetLayout: vi.fn(),
  updateEdgeStyle: vi.fn(),
  resetEdgeStyle: vi.fn(),
  updateInterfaceOverride: vi.fn(),
  resetInterfaceOverride: vi.fn(),
  getVisualTopology: vi.fn(),
  createVisualElement: vi.fn(),
  updateVisualElement: vi.fn(),
  deleteVisualElement: vi.fn(),
  addRackMember: vi.fn(),
  removeRackMember: vi.fn(),
  createVisualLink: vi.fn(),
  updateVisualLink: vi.fn(),
  deleteVisualLink: vi.fn(),
  updateEdgeRoute: vi.fn(),
  resetEdgeRoute: vi.fn(),
}));

const setThemeMock = vi.hoisted(() => vi.fn());
const topologyEventsMock = vi.hoisted(() => ({
  onEvent: null as ((event: TopologyEvent) => void) | null,
}));

vi.mock("./services/api", () => ({
  api: apiMocks,
  ApiError: class ApiError extends Error {},
}));

vi.mock("./hooks/useTopologyEvents", () => ({
  useTopologyEvents: (onEvent: (event: TopologyEvent) => void) => {
    topologyEventsMock.onEvent = onEvent;
    return false;
  },
}));

vi.mock("./hooks/useTheme", () => ({
  useTheme: () => ({
    preference: "system",
    resolvedTheme: "light",
    setPreference: setThemeMock,
  }),
}));

vi.mock("./components/canvas/TopologyCanvas", () => ({
  TopologyCanvas: ({
    snapshot,
    onConfigureEdge,
    onSelectNode,
    onSelectVisual,
  }: {
    snapshot: TopologySnapshot;
    onConfigureEdge: (edgeId: string) => void;
    onSelectNode: (node: ConnectionNode) => void;
    onSelectVisual: (element: VisualElement) => void;
  }) => {
    const rack = snapshot.visual_topology?.elements.find((element) => element.type === "rack");
    return (
    <div data-testid="topology-canvas">
      <button
        type="button"
        onClick={() => onConfigureEdge(`sdex-to-${snapshot.nodes[0]?.id}`)}
      >
        Open edge style
      </button>
      <button
        type="button"
        onClick={() => {
          const node = snapshot.nodes[0];
          if (node) onSelectNode(node);
        }}
      >
        Open node details
      </button>
      {rack && (
        <>
          <button type="button" onClick={() => onSelectVisual(rack)}>
            Open Rack properties
          </button>
          <output aria-label="Rendered Rack dimensions">{rack.rows} by {rack.columns}</output>
        </>
      )}
    </div>
    );
  },
}));

import App from "./App";

function makeRackSnapshot(rows = 1, columns = 3): TopologySnapshot {
  const snapshot = makeSnapshot();
  return {
    ...snapshot,
    visual_topology: {
      elements: [{
        id: "rack-1", type: "rack", name: "Production Rack", description: null,
        rows, columns, capacity: rows * columns, collapsed: false,
        position: { x: -600, y: 0 }, width: 400, height: 300,
        external_interface: "eth1", schema_version: 1,
        created_at: "2026-07-28T08:30:00Z", updated_at: "2026-07-28T08:30:00Z",
        aggregate: {
          status: "connected", total: 2, connected: 2, disconnected: 0,
          disabled: 0, unknown: 0, degraded: 0, missing: 0, animated: true,
        },
      }],
      rack_memberships: snapshot.nodes.map((connection, column) => ({
        rack_id: "rack-1", connection_id: connection.id, row: 0, column,
        connection, missing: false,
      })),
      links: [], routes: {}, unrouted_connection_ids: [],
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

describe("App refresh fallback", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.clearAllMocks();
    topologyEventsMock.onEvent = null;
    apiMocks.getConfigStatus.mockResolvedValue({
      configured: true,
      source: "database",
      base_url: "https://sdex-suite",
      username: "viewer",
      verify_tls: true,
      timeout_seconds: 15,
      password_configured: true,
      mock_mode: false,
      tls_warning: false,
    });
    apiMocks.getSettings.mockResolvedValue({
      refresh_interval_seconds: 300,
      allowed_refresh_intervals: [60, 300, 600, 900, 1800, 3600],
      show_not_enabled: false,
      theme: "system",
      network_interfaces: [],
    });
    apiMocks.refreshTopology.mockResolvedValue({
      accepted: true,
      in_progress: true,
      correlation_id: "refresh-1",
    });
    apiMocks.saveLayout.mockResolvedValue({ ok: true });
    apiMocks.resetLayout.mockResolvedValue({ ok: true });
    apiMocks.updateEdgeStyle.mockResolvedValue({
      edge_id: "sdex-to-modbus:line-1",
      sheath_color: "#123456",
      flow_color: "#4DA3FF",
      updated_at: "2026-07-29T10:00:00Z",
      schema_version: 1,
    });
    apiMocks.resetEdgeStyle.mockResolvedValue({ ok: true });
    apiMocks.updateInterfaceOverride.mockResolvedValue({ ok: true });
    apiMocks.resetInterfaceOverride.mockResolvedValue({ ok: true });
    apiMocks.resetEdgeRoute.mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps polling after 700ms until a refresh completes without SSE", async () => {
    apiMocks.getTopology
      .mockResolvedValueOnce(makeSnapshot())
      .mockResolvedValueOnce(
        makeSnapshot(undefined, { refresh_in_progress: true }),
      )
      .mockResolvedValueOnce(
        makeSnapshot(undefined, {
          refresh_in_progress: false,
          generated_at: "2026-07-28T08:31:00Z",
        }),
      );

    render(<App />);
    const refresh = await screen.findByRole("button", { name: /Refresh now/i });
    fireEvent.click(refresh);

    await waitFor(() => expect(apiMocks.refreshTopology).toHaveBeenCalledOnce());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(apiMocks.getTopology).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /Refreshing/i })).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(apiMocks.getTopology).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("button", { name: /Refresh now/i })).toBeEnabled();
  });

  it("keeps edge configuration and node details mutually exclusive", async () => {
    vi.useRealTimers();
    const user = userEvent.setup();
    apiMocks.getTopology.mockResolvedValue(makeSnapshot());

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Open edge style" }));
    expect(
      screen.getByRole("dialog", { name: "Cable appearance" }),
    ).toBeVisible();
    expect(screen.queryByTestId("details-drawer")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open node details" }));
    expect(screen.getByTestId("details-drawer")).toBeVisible();
    expect(
      screen.queryByRole("dialog", { name: "Cable appearance" }),
    ).not.toBeInTheDocument();
  });

  it("does not overwrite a saved Rack with a topology response started before the save", async () => {
    vi.useRealTimers();
    const before = makeRackSnapshot();
    const after = makeRackSnapshot(2, 2);
    const oldRead = deferred<TopologySnapshot>();
    apiMocks.getTopology.mockResolvedValueOnce(before);
    apiMocks.updateVisualElement.mockResolvedValue(after.visual_topology?.elements[0]);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open Rack properties" }));
    fireEvent.click(screen.getByText("Editor", { exact: true }));
    apiMocks.getTopology.mockReturnValueOnce(oldRead.promise).mockResolvedValueOnce(after);
    act(() => topologyEventsMock.onEvent?.({ type: "topology.updated" }));
    expect(apiMocks.getTopology).toHaveBeenCalledTimes(2);

    fireEvent.change(screen.getByLabelText("Rows"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Columns"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Rack" }));
    await waitFor(() => expect(screen.getByLabelText("Rendered Rack dimensions"))
      .toHaveTextContent("2 by 2"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save Rack" })).toBeEnabled());
    await act(async () => { oldRead.resolve(before); await oldRead.promise; });
    expect(screen.getByLabelText("Rendered Rack dimensions")).toHaveTextContent("2 by 2");
    expect(screen.getByLabelText("Rows")).toHaveValue(2);
    expect(screen.getByLabelText("Columns")).toHaveValue(2);
    expect(apiMocks.updateVisualElement).toHaveBeenCalledWith("rack-1", expect.objectContaining({
      rows: 2, columns: 2,
    }));
  });

  it("does not stop refresh polling when an older topology event response finishes", async () => {
    const oldRead = deferred<TopologySnapshot>();
    apiMocks.getTopology
      .mockResolvedValueOnce(makeSnapshot())
      .mockReturnValueOnce(oldRead.promise)
      .mockResolvedValueOnce(makeSnapshot(undefined, { refresh_in_progress: true }))
      .mockResolvedValueOnce(makeSnapshot(undefined, { refresh_in_progress: false }));
    render(<App />);
    const refresh = await screen.findByRole("button", { name: /Refresh now/i });
    act(() => topologyEventsMock.onEvent?.({ type: "topology.updated" }));
    expect(apiMocks.getTopology).toHaveBeenCalledTimes(2);
    fireEvent.click(refresh);
    await waitFor(() => expect(apiMocks.refreshTopology).toHaveBeenCalledOnce());
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(apiMocks.getTopology).toHaveBeenCalledTimes(3);

    await act(async () => { oldRead.resolve(makeSnapshot()); await oldRead.promise; });
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(apiMocks.getTopology).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("button", { name: /Refresh now/i })).toBeEnabled();
  });
});
