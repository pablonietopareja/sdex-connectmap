import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeSnapshot } from "./test/fixtures";
import type { ConnectionNode, TopologySnapshot } from "./types";

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

vi.mock("./services/api", () => ({
  api: apiMocks,
  ApiError: class ApiError extends Error {},
}));

vi.mock("./hooks/useTopologyEvents", () => ({
  useTopologyEvents: () => false,
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
  }: {
    snapshot: TopologySnapshot;
    onConfigureEdge: (edgeId: string) => void;
    onSelectNode: (node: ConnectionNode) => void;
  }) => (
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
    </div>
  ),
}));

import App from "./App";

describe("App refresh fallback", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.clearAllMocks();
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
});
