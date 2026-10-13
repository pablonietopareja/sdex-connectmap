import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EdgeProps, NodeProps } from "@xyflow/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CONNECTION_PRESENTATION } from "../constants";
import { DEVICE_TYPES, makeGateway, makeNode, makeSnapshot } from "../test/fixtures";
import type {
  ConnectionStatus,
  EdgeVisualStyle,
  NetworkInterface,
} from "../types";
import type {
  ConnectionFlowNode,
  DataCableFlowEdge,
  GatewayFlowNode,
} from "./canvas/types";

vi.mock("@xyflow/react", () => ({
  Handle: ({
    id,
    type,
    position,
    "aria-label": ariaLabel,
  }: {
    id: string;
    type: string;
    position: string;
    "aria-label"?: string;
  }) => (
    <span
      data-testid="flow-handle"
      data-handle-id={id}
      data-handle-type={type}
      data-handle-position={position}
      aria-label={ariaLabel}
    />
  ),
  Position: {
    Left: "left",
    Right: "right",
    Top: "top",
    Bottom: "bottom",
  },
  EdgeLabelRenderer: ({ children }: { children: React.ReactNode }) => (
    <foreignObject>{children}</foreignObject>
  ),
  getBezierPath: () => ["M 0 0 C 20 0 80 0 100 0", 50, 0],
  useReactFlow: () => ({
    screenToFlowPosition: ({ x, y }: { x: number; y: number }) => ({ x, y }),
    setNodes: vi.fn(),
    setEdges: vi.fn(),
  }),
  useViewport: () => ({ x: 0, y: 0, zoom: 1 }),
}));

import { ConnectionNodeCard } from "./nodes/ConnectionNodeCard";
import { GatewayNodeCard } from "./nodes/GatewayNodeCard";
import { DataCableEdge } from "./edges/DataCableEdge";
import { DetailsDrawer } from "./DetailsDrawer";
import { SummaryPanel } from "./SummaryPanel";
import { TopBar } from "./TopBar";
import { TopologyAlerts } from "./TopologyAlerts";

function connectionProps(
  node = makeNode(),
  onOpen = vi.fn(),
): NodeProps<ConnectionFlowNode> {
  return {
    id: node.id,
    type: "connection",
    data: { connection: node, editorEnabled: false, onOpen },
    selected: false,
    dragging: false,
    draggable: false,
    selectable: true,
    deletable: false,
    isConnectable: false,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    zIndex: 1,
  } as unknown as NodeProps<ConnectionFlowNode>;
}

function gatewayProps(
  networkInterfaces: NetworkInterface[] = [],
): NodeProps<GatewayFlowNode> {
  const gateway = makeGateway();
  return {
    id: gateway.id,
    type: "gateway",
    data: { connection: gateway, networkInterfaces, onOpen: vi.fn() },
    selected: false,
    dragging: false,
    draggable: false,
    selectable: true,
    deletable: false,
    isConnectable: false,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    zIndex: 1,
  } as unknown as NodeProps<GatewayFlowNode>;
}

function edgeProps(
  status: ConnectionStatus,
  style: EdgeVisualStyle | null = null,
  onConfigure = vi.fn(),
) {
  return {
    id: `edge-${status}`,
    source: "device",
    target: "sdex",
    sourceX: 0,
    sourceY: 0,
    targetX: 100,
    targetY: 0,
    sourcePosition: "right",
    targetPosition: "left",
    data: {
      status,
      stale: false,
      style,
      connectionName: "Test device",
      networkInterface: "eth1",
      onConfigure,
    },
  } as unknown as EdgeProps<DataCableFlowEdge>;
}

describe("connection nodes", () => {
  it.each(DEVICE_TYPES)(
    "renders only the supplied name in the header and the contained SVG for %s",
    (type) => {
    const node = makeNode({
      id: `${type}:test`,
      type,
      display_name: `Test ${type}`,
      subtype: "Test subtype",
    });
    const { container, unmount } = render(
      <ConnectionNodeCard {...connectionProps(node)} />,
    );

    const card = screen.getByTestId(`connection-node-${type}`);
    const header = card.querySelector(".node-header");
    expect(header).toHaveTextContent(`Test ${type}`);
    expect(header).not.toHaveTextContent(
      CONNECTION_PRESENTATION[type].shortLabel,
    );
    expect(header?.querySelector(".node-type")).not.toBeInTheDocument();
    expect(container.querySelector(".node-icon-shell > img")).toHaveAttribute(
      "src",
      CONNECTION_PRESENTATION[type].icon,
    );
    expect(container.querySelector(".node-status-area")).toContainElement(
      screen.getByTestId("status-connected"),
    );
    expect(container.querySelector(".node-footer")).not.toBeInTheDocument();
    unmount();
    },
  );

  it("opens details from double-click and keyboard, not a single click", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<ConnectionNodeCard {...connectionProps(makeNode(), onOpen)} />);
    const card = screen.getByRole("button");

    await user.click(card);
    expect(onOpen).not.toHaveBeenCalled();
    await user.dblClick(card);
    card.focus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("renders the fixed SDEX gateway with one title and interface-aligned labels", () => {
    const networkInterfaces: NetworkInterface[] = [
      {
        name: "eth1",
        source: "mock",
        addresses: [
          {
            address: "192.168.10.1",
            prefix_length: 24,
            network: "192.168.10.0/24",
            version: 4,
          },
        ],
      },
      {
        name: "eth2",
        source: "mock",
        addresses: [
          {
            address: "192.168.20.1",
            prefix_length: 24,
            network: "192.168.20.0/24",
            version: 4,
          },
        ],
      },
    ];
    const { container } = render(
      <GatewayNodeCard {...gatewayProps(networkInterfaces)} />,
    );
    expect(screen.getByTestId("gateway-node")).toBeInTheDocument();
    expect(screen.getByText("Locked")).toBeVisible();
    const header = container.querySelector(".gateway-header");
    expect(header).toHaveTextContent("SDEX Suite");
    expect(within(header as HTMLElement).getByText("SDEX Suite")).toBeVisible();
    expect(screen.queryByText("SDEX Gateway")).not.toBeInTheDocument();

    const eth1 = container.querySelector(
      ".gateway-interface-label--top[data-interface='eth1']",
    );
    const eth2 = container.querySelector(
      ".gateway-interface-label--bottom[data-interface='eth2']",
    );
    expect(eth1).toHaveTextContent("eth1");
    expect(eth1).toHaveTextContent("192.168.10.1/24");
    expect(eth2).toHaveTextContent("eth2");
    expect(eth2).toHaveTextContent("192.168.20.1/24");

    const statusArea = container.querySelector(".gateway-status-area");
    expect(statusArea?.children[0]).toBe(screen.getByTestId("status-connected"));
    expect(statusArea?.children[1]).toHaveTextContent("Locked");

    const handles = screen.getAllByTestId("flow-handle");
    expect(handles).toHaveLength(2);
    expect(handles[0]).toHaveAttribute("data-handle-id", "sdex-eth1");
    expect(handles[0]).toHaveAttribute("data-handle-type", "target");
    expect(handles[0]).toHaveAttribute("data-handle-position", "top");
    expect(handles[1]).toHaveAttribute("data-handle-id", "sdex-eth2");
    expect(handles[1]).toHaveAttribute("data-handle-type", "target");
    expect(handles[1]).toHaveAttribute("data-handle-position", "bottom");
  });
});

describe("data cable edge", () => {
  it("animates only a connected cable", () => {
    const { container } = render(
      <svg>
        <DataCableEdge {...edgeProps("connected")} />
      </svg>,
    );
    expect(container.querySelector(".edge-data-flow")).toHaveAttribute(
      "data-flow-direction",
      "forward",
    );
    expect(container.querySelector(".edge-data-flow")).toHaveStyle({
      animationDirection: "normal",
    });
    expect(screen.getByTestId("edge-connected")).toBeInTheDocument();
  });

  it("reverses the real per-edge dash animation when requested", () => {
    const style: EdgeVisualStyle = {
      edge_id: "edge-connected",
      sheath_color: "#123456",
      flow_color: "#ABCDEF",
      reverse_flow: true,
      updated_at: "2026-07-29T10:00:00Z",
      schema_version: 1,
    };
    const { container } = render(
      <svg>
        <DataCableEdge {...edgeProps("connected", style)} />
      </svg>,
    );

    expect(screen.getByTestId("edge-connected")).toHaveAttribute(
      "data-flow-direction",
      "reverse",
    );
    expect(container.querySelector(".edge-data-flow")).toHaveClass(
      "edge-data-flow-reverse",
    );
    expect(container.querySelector(".edge-data-flow")).toHaveStyle({
      animationDirection: "reverse",
    });
  });

  it("shows a broken, non-animated disconnected cable", () => {
    const { container } = render(
      <svg>
        <DataCableEdge {...edgeProps("disconnected")} />
      </svg>,
    );
    expect(container.querySelector(".edge-data-flow")).not.toBeInTheDocument();
    expect(screen.getByText("Communication lost")).toBeVisible();
    expect(screen.getByTestId("edge-disconnected")).toHaveClass("edge-disconnected");
  });

  it("opens configuration from a double-click on an edge status label", async () => {
    const user = userEvent.setup();
    const onConfigure = vi.fn();
    render(
      <svg>
        <DataCableEdge
          {...edgeProps("disconnected", null, onConfigure)}
        />
      </svg>,
    );

    await user.dblClick(
      screen.getByRole("status", { name: "Communication lost" }),
    );
    expect(onConfigure).toHaveBeenCalledWith("edge-disconnected");
  });

  it("does not present an unknown state as disconnected", () => {
    render(
      <svg>
        <DataCableEdge {...edgeProps("unknown")} />
      </svg>,
    );
    expect(screen.getByText("Status unavailable")).toBeVisible();
    expect(screen.queryByText("Communication lost")).not.toBeInTheDocument();
  });

  it("applies only validated per-edge colors through CSS variables", () => {
    const style: EdgeVisualStyle = {
      edge_id: "edge-connected",
      sheath_color: "#123456",
      flow_color: "#ABCDEF",
      reverse_flow: false,
      updated_at: "2026-07-29T10:00:00Z",
      schema_version: 1,
    };
    const { container, rerender } = render(
      <svg>
        <DataCableEdge {...edgeProps("connected", style)} />
      </svg>,
    );
    const edge = screen.getByTestId("edge-connected");
    expect(edge.style.getPropertyValue("--edge-sheath-color")).toBe("#123456");
    expect(edge.style.getPropertyValue("--edge-flow-color")).toBe("#ABCDEF");
    expect(container.querySelector(".edge-cable-base")).toHaveStyle({
      stroke: "var(--edge-sheath-color)",
    });

    rerender(
      <svg>
        <DataCableEdge
          {...edgeProps("connected", {
            ...style,
            sheath_color: "url(javascript:alert(1))",
          })}
        />
      </svg>,
    );
    expect(
      screen
        .getByTestId("edge-connected")
        .style.getPropertyValue("--edge-sheath-color"),
    ).toBe("");
  });
});

describe("details, counts and operational state", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders connection details, SINUMERIK subchannels, and filters secrets", () => {
    const node = makeNode({
      type: "sinumerik_840d",
      subtype: "840D sl",
      endpoint_url: "opc.tcp://10.20.0.41:4840",
      capabilities: {
        subchannels: {
          nck: { enabled: true, status: "connected" },
          plc: {
            enabled: true,
            status: "disconnected",
            reason: "PLC channel unavailable",
          },
        },
      },
      metadata: {
        station: "Cell 4",
        auth_token: "must-not-render",
        nested: { password: "must-not-render" },
      },
    });
    render(<DetailsDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByTestId("details-drawer")).toBeVisible();
    expect(screen.getByText("840D sl")).toBeVisible();
    expect(screen.getByText("NCK")).toBeVisible();
    expect(screen.getByText("PLC")).toBeVisible();
    expect(screen.getByText("Cell 4")).toBeVisible();
    expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
  });

  it("renders a prominent SDEX icon and both reported network interfaces", () => {
    const { container } = render(
      <DetailsDrawer
        node={makeGateway()}
        networkInterfaces={[
          {
            name: "eth1",
            source: "mock",
            addresses: [
              {
                address: "192.168.10.1",
                prefix_length: 24,
                network: "192.168.10.0/24",
                version: 4,
              },
            ],
          },
          {
            name: "eth2",
            source: "mock",
            addresses: [
              {
                address: "192.168.20.1",
                prefix_length: 24,
                network: "192.168.20.0/24",
                version: 4,
              },
            ],
          },
        ]}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Network interfaces" })).toBeVisible();
    expect(screen.getByText("192.168.10.1/24")).toBeVisible();
    expect(screen.getByText("192.168.20.1/24")).toBeVisible();
    expect(container.querySelector(".details-icon img")).toHaveAttribute(
      "src",
      CONNECTION_PRESENTATION.sdex_gateway.icon,
    );
  });

  it("renders exact topology counts and keeps both OPC UA categories", () => {
    const snapshot = makeSnapshot([
      makeNode(),
      makeNode({
        id: "remote:a",
        type: "opcua_remote_server",
        status: "unknown",
      }),
      makeNode({
        id: "local:a",
        type: "opcua_local_endpoint",
        enabled: false,
        status: "disabled",
      }),
    ]);
    render(
      <SummaryPanel
        summary={snapshot.summary}
        collapsed={false}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("3 configured")).toBeVisible();
    expect(screen.getByText("OPC UA Servers")).toBeVisible();
    expect(screen.getByText("OPC UA Endpoints")).toBeVisible();
    expect(screen.getByText("Unknown / degraded")).toBeVisible();
  });

  it("shows stale communication separately from device disconnection", () => {
    render(
      <TopologyAlerts
        snapshot={makeSnapshot(undefined, {
          stale: true,
          last_error: "SDEX request timed out",
        })}
      />,
    );
    expect(
      screen.getByText(/Communication with SDEX is unavailable/i),
    ).toBeVisible();
    expect(screen.getByText(/last valid snapshot remains visible/i)).toBeVisible();
  });
});

describe("top bar controls", () => {
  function renderBar(overrides: Partial<React.ComponentProps<typeof TopBar>> = {}) {
    const props: React.ComponentProps<typeof TopBar> = {
      snapshot: makeSnapshot(undefined, { mock_mode: true }),
      editorEnabled: false,
      showNotEnabled: false,
      refreshInterval: 300,
      theme: "system",
      eventsConnected: true,
      tlsWarning: false,
      onEditorChange: vi.fn(),
      onShowNotEnabledChange: vi.fn(),
      onRefreshIntervalChange: vi.fn(),
      onThemeChange: vi.fn(),
      onRefresh: vi.fn(),
      onOpenSettings: vi.fn(),
      ...overrides,
    };
    render(<TopBar {...props} />);
    return props;
  }

  it("contains exactly the required refresh intervals and persists selection intent", async () => {
    const user = userEvent.setup();
    const props = renderBar();
    const select = screen.getByRole("combobox", { name: "Refresh interval" });
    await user.click(select);
    expect(
      screen
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "1 minute",
      "5 minutes",
      "10 minutes",
      "15 minutes",
      "30 minutes",
      "1 hour",
    ]);
    await user.click(screen.getByRole("option", { name: "15 minutes" }));
    expect(props.onRefreshIntervalChange).toHaveBeenCalledWith(900);
  });

  it("toggles Editor and Show not enabled independently", async () => {
    const user = userEvent.setup();
    const props = renderBar();
    await user.click(screen.getByRole("switch", { name: "Editor" }));
    await user.click(screen.getByRole("switch", { name: "Show not enabled" }));
    expect(props.onEditorChange).toHaveBeenCalledWith(true);
    expect(props.onShowNotEnabledChange).toHaveBeenCalledWith(true);
  });

  it("changes theme and clearly identifies Mock Mode", async () => {
    const user = userEvent.setup();
    const props = renderBar();
    expect(
      screen.getByLabelText("Data source: Mock Mode"),
    ).toHaveTextContent("Mock Mode");
    expect(screen.queryByText("Real SDEX")).not.toBeInTheDocument();
    const theme = screen.getByRole("combobox", { name: "Theme" });
    await user.click(theme);
    await user.keyboard("{ArrowUp}{Enter}");
    expect(props.onThemeChange).toHaveBeenCalledWith("dark");
  });

  it("clearly identifies the configured real SDEX data source", () => {
    renderBar({
      snapshot: makeSnapshot(undefined, { mock_mode: false }),
    });

    expect(
      screen.getByLabelText("Data source: Real SDEX"),
    ).toHaveTextContent("Real SDEX");
    expect(screen.queryByText("Mock Mode")).not.toBeInTheDocument();
  });

  it("keeps disabled TLS verification visible in the compact alarm centre", async () => {
    const user = userEvent.setup();
    renderBar({
      tlsWarning: true,
      snapshot: makeSnapshot(undefined, { mock_mode: false }),
    });
    await user.click(screen.getByRole("button", { name: "Alarms, 1 active" }));
    expect(
      screen.getByText("TLS certificate verification is disabled"),
    ).toBeVisible();
  });

  it("uses the official ConnectMap logo without replacing the brand text", () => {
    renderBar();
    expect(document.querySelector(".brand > .brand-logo")).toHaveAttribute(
      "src",
      "/icons/SDEX_ConnectMap_logo.svg",
    );
    expect(document.querySelector(".brand > .brand-mark")).not.toBeInTheDocument();
    expect(screen.getByText("SDEX ConnectMap")).toBeVisible();
    expect(screen.getByText("by Pablo")).toBeVisible();
  });
});
