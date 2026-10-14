import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Node, NodeProps } from "@xyflow/react";
import type { CSSProperties, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeGateway, makeNode } from "../../test/fixtures";
import type { ConnectionFlowNode, GatewayFlowNode } from "../canvas/types";
import type { RackFlowNode } from "../nodes/RackNodeCard";
import type { SwitchFlowNode } from "../nodes/SwitchNodeCard";
import type { RackElementView, SwitchElementView } from "./types";

const updateNodeInternals = vi.fn();

vi.mock("@xyflow/react", () => ({
  Handle: ({
    id,
    type,
    position,
    style,
    "aria-label": ariaLabel,
  }: {
    id: string;
    type: string;
    position: string;
    style?: CSSProperties;
    "aria-label"?: string;
  }) => (
    <span
      data-testid="flow-handle"
      data-handle-id={id}
      data-handle-type={type}
      data-handle-position={position}
      aria-label={ariaLabel}
      style={style}
    />
  ),
  Position: {
    Left: "left",
    Right: "right",
    Top: "top",
    Bottom: "bottom",
  },
  useUpdateNodeInternals: () => updateNodeInternals,
  ReactFlowProvider: ({ children }: { children: ReactNode }) => children,
}));

import {
  EditorToolbar,
  VISUAL_ELEMENT_DRAG_TYPE,
  readVisualToolDrag,
} from "./EditorToolbar";
import { RackPropertiesPanel } from "./RackPropertiesPanel";
import { SwitchPropertiesPanel } from "./SwitchPropertiesPanel";
import { DetailsDrawer } from "../DetailsDrawer";
import { ConnectionNodeCard } from "../nodes/ConnectionNodeCard";
import { GatewayNodeCard } from "../nodes/GatewayNodeCard";
import {
  EMBEDDED_CONNECTION_HEIGHT,
  EMBEDDED_CONNECTION_WIDTH,
  RackNodeCard,
  rackDimensions,
  rackSlotPosition,
} from "../nodes/RackNodeCard";
import { SWITCH_ICON, SwitchNodeCard } from "../nodes/SwitchNodeCard";

function baseNodeProps<TNode extends Node>(
  id: string,
  type: string,
  data: TNode["data"],
): NodeProps<TNode> {
  return {
    id,
    type,
    data,
    selected: false,
    dragging: false,
    draggable: true,
    selectable: true,
    deletable: false,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    zIndex: 1,
  };
}

function rack(overrides: Partial<RackElementView> = {}): RackElementView {
  return {
    id: "rack-1",
    type: "rack",
    name: "Production Line 1",
    rows: 1,
    columns: 3,
    capacity: 3,
    member_ids: [],
    slot_assignments: [],
    external_interface: "eth1",
    ...overrides,
  };
}

function visualSwitch(
  overrides: Partial<SwitchElementView> = {},
): SwitchElementView {
  return {
    id: "switch-1",
    type: "switch",
    name: "Line switch",
    description: "Aggregates the cell topology",
    external_interface: "eth2",
    ...overrides,
  };
}

describe("advanced editor toolbar", () => {
  it("is hidden outside Editor and offers only Rack and Switch inside Editor", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    const { rerender } = render(
      <EditorToolbar visible={false} onCreate={onCreate} />,
    );
    expect(screen.queryByTestId("editor-toolbar")).not.toBeInTheDocument();

    rerender(<EditorToolbar visible onCreate={onCreate} />);
    const toolbar = screen.getByTestId("editor-toolbar");
    const tools = within(toolbar).getAllByRole("button", { name: /^Add / });
    expect(tools).toHaveLength(2);
    expect(within(toolbar).getByRole("button", { name: "Add Rack" })).toBeVisible();
    expect(within(toolbar).getByRole("button", { name: "Add Switch" })).toBeVisible();
    expect(toolbar.querySelector("img")).toHaveAttribute("src", SWITCH_ICON);
    expect(within(toolbar).getByRole("button", { name: "Undo visual change" })).toBeDisabled();
    expect(within(toolbar).getByRole("button", { name: "Redo visual change" })).toBeDisabled();

    await user.click(within(toolbar).getByRole("button", { name: "Add Rack" }));
    expect(onCreate).toHaveBeenCalledWith("rack");
  });

  it("writes and reads a namespaced drag payload", () => {
    const payload = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "none",
      setData: (type: string, value: string) => payload.set(type, value),
      getData: (type: string) => payload.get(type) ?? "",
    } as unknown as DataTransfer;
    render(<EditorToolbar visible onCreate={vi.fn()} />);

    fireEvent.dragStart(screen.getByRole("button", { name: "Add Switch" }), {
      dataTransfer,
    });

    expect(payload.get(VISUAL_ELEMENT_DRAG_TYPE)).toBe("switch");
    expect(readVisualToolDrag(dataTransfer)).toBe("switch");
  });
});

describe("Rack presentation", () => {
  it("uses deterministic geometry matching embedded child positions", () => {
    expect(rackDimensions(2, 3)).toEqual({
      width: 40 + EMBEDDED_CONNECTION_WIDTH * 3 + 16 * 2,
      height: 64 + 16 + EMBEDDED_CONNECTION_HEIGHT * 2 + 16 + 52,
    });
    expect(rackSlotPosition(1, 2)).toEqual({
      x: 20 + 2 * (EMBEDDED_CONNECTION_WIDTH + 16),
      y: 64 + 16 + EMBEDDED_CONNECTION_HEIGHT + 16,
    });
  });

  it("renders missing, occupied and accessible empty slots without duplicating members", () => {
    const element = rack({
      member_ids: ["device-present", "device-missing"],
      slot_assignments: [
        { row: 0, column: 0, connection_id: "device-present" },
        { row: 0, column: 1, connection_id: "device-missing" },
      ],
    });
    const props = baseNodeProps<RackFlowNode>(element.id, "rack", {
      rack: element,
      editorEnabled: true,
      aggregateStatus: "degraded",
      aggregateCounts: {
        total: 2,
        connected: 1,
        disconnected: 1,
        unknown: 0,
        disabled: 0,
      },
      missingMemberIds: ["device-missing"],
      onOpen: vi.fn(),
    });

    const { container } = render(<RackNodeCard {...props} />);
    expect(container.querySelectorAll(".rack-slot")).toHaveLength(3);
    expect(container.querySelectorAll(".rack-slot-occupied")).toHaveLength(1);
    expect(screen.getByText("Connection unavailable")).toBeVisible();
    const emptySlot = screen.getByRole("img", {
      name: "Empty rack slot 1, 3. Drop a connection here.",
    });
    expect(emptySlot).toBeVisible();
    expect(emptySlot.tagName).toBe("DIV");
    expect(container.querySelector(".connection-node-card")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("flow-handle").map((handle) => handle.dataset.handlePosition))
      .toEqual(["left", "right"]);
  });

  it("reuses ConnectionNodeCard in an embedded, handle-free variant", () => {
    const node = makeNode({ display_name: "Rack member" });
    const props = baseNodeProps<ConnectionFlowNode>(node.id, "connection", {
      connection: node,
      editorEnabled: true,
      variant: "embedded",
      rackId: "rack-1",
      onOpen: vi.fn(),
    });

    render(<ConnectionNodeCard {...props} />);
    expect(screen.getByTestId(`connection-node-${node.type}`)).toHaveAttribute(
      "data-variant",
      "embedded",
    );
    expect(screen.queryByTestId("flow-handle")).not.toBeInTheDocument();
  });
});

describe("Switch presentation", () => {
  beforeEach(() => updateNodeInternals.mockClear());

  it("uses the canonical Switch.svg and distributes handles only left/right", async () => {
    const element = visualSwitch();
    const props = baseNodeProps<SwitchFlowNode>(element.id, "switch", {
      visualSwitch: element,
      editorEnabled: true,
      handles: [
        { id: "left:visual-link:one", side: "left", type: "target" },
        { id: "left:visual-link:two", side: "left", type: "target" },
        { id: "left:visual-link:three", side: "left", type: "target" },
        { id: "left:new", side: "left", type: "target" },
        { id: "right:new", side: "right", type: "source" },
      ],
      onOpen: vi.fn(),
    });

    render(<SwitchNodeCard {...props} />);
    expect(screen.getByTestId("switch-node").querySelector("img")).toHaveAttribute(
      "src",
      "/icons/Switch.svg",
    );
    const positions = screen
      .getAllByTestId("flow-handle")
      .map((handle) => handle.dataset.handlePosition);
    expect(positions).toEqual(["left", "left", "left", "left", "right"]);
    expect(positions).not.toContain("top");
    expect(positions).not.toContain("bottom");
    expect(screen.getByText("3 visual links")).toBeInTheDocument();
    await waitFor(() => expect(updateNodeInternals).toHaveBeenCalledWith(element.id));
  });
});

describe("visual element property panels", () => {
  it("preserves a Rack draft when live topology updates only its aggregate or position", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const callbacks = {
      onClose: vi.fn(),
      onSave,
      onUngroupAll: vi.fn().mockResolvedValue(undefined),
      onDelete: vi.fn().mockResolvedValue(undefined),
    };
    const { rerender } = render(
      <RackPropertiesPanel rack={rack()} {...callbacks} />,
    );
    fireEvent.change(screen.getByLabelText("Rows"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Columns"), { target: { value: "2" } });

    rerender(
      <RackPropertiesPanel
        rack={rack({
          position: { x: 100, y: 200 },
          aggregate: {
            status: "connected", total: 2, connected: 2,
            disconnected: 0, disabled: 0, unknown: 0,
          },
        })}
        {...callbacks}
      />,
    );
    expect(screen.getByLabelText("Rows")).toHaveValue(2);
    expect(screen.getByLabelText("Columns")).toHaveValue(2);
    fireEvent.click(screen.getByRole("button", { name: "Save Rack" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(
      "rack-1",
      expect.objectContaining({ rows: 2, columns: 2 }),
      { expelOverflow: false },
    ));
  });

  it("loads persisted Rack dimensions and a different Rack when the selected element changes", () => {
    const callbacks = {
      onClose: vi.fn(),
      onSave: vi.fn().mockResolvedValue(undefined),
      onUngroupAll: vi.fn().mockResolvedValue(undefined),
      onDelete: vi.fn().mockResolvedValue(undefined),
    };
    const { rerender } = render(
      <RackPropertiesPanel rack={rack()} {...callbacks} />,
    );
    rerender(
      <RackPropertiesPanel rack={rack({ rows: 2, columns: 2 })} {...callbacks} />,
    );
    expect(screen.getByLabelText("Rows")).toHaveValue(2);
    expect(screen.getByLabelText("Columns")).toHaveValue(2);
    fireEvent.change(screen.getByLabelText("Rows"), { target: { value: "3" } });
    rerender(
      <RackPropertiesPanel rack={rack({ id: "rack-2", rows: 1, columns: 2 })} {...callbacks} />,
    );
    expect(screen.getByLabelText("Rows")).toHaveValue(1);
    expect(screen.getByLabelText("Columns")).toHaveValue(2);
  });

  it("requires confirmation and expels overflow when shrinking an occupied Rack", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <RackPropertiesPanel
        rack={rack({
          member_ids: ["device-1", "device-2"],
          aggregate: {
            status: "degraded",
            total: 2,
            connected: 1,
            disconnected: 1,
            unknown: 0,
            disabled: 0,
            degraded: 1,
            missing: 1,
          },
        })}
        onClose={vi.fn()}
        onSave={onSave}
        onUngroupAll={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByLabelText("Aggregate Rack status")).toHaveTextContent(
      "1 connected, 1 disconnected, 0 unknown, 0 disabled, 1 degraded, 1 missing",
    );

    const columns = screen.getByLabelText("Columns");
    await user.clear(columns);
    await user.type(columns, "1");
    await user.click(screen.getByRole("button", { name: "Save Rack" }));
    expect(screen.getByText("Members fall outside the new layout")).toBeVisible();
    expect(onSave).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Expel overflow and save" }),
    );
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        "rack-1",
        expect.objectContaining({ rows: 1, columns: 1 }),
        { expelOverflow: true },
      ),
    );
  });

  it("requires confirmation when a Rack reshape leaves a member out of bounds", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <RackPropertiesPanel
        rack={rack({
          rows: 2,
          columns: 2,
          capacity: 4,
          member_ids: ["device-1"],
          slot_assignments: [
            { row: 1, column: 0, connection_id: "device-1" },
          ],
        })}
        onClose={vi.fn()}
        onSave={onSave}
        onUngroupAll={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const rows = screen.getByLabelText("Rows");
    const columns = screen.getByLabelText("Columns");
    await user.clear(rows);
    await user.type(rows, "1");
    await user.clear(columns);
    await user.type(columns, "4");
    await user.click(screen.getByRole("button", { name: "Save Rack" }));

    expect(screen.getByText("Members fall outside the new layout")).toBeVisible();
    expect(onSave).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Expel overflow and save" }),
    );
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        "rack-1",
        expect.objectContaining({ rows: 1, columns: 4 }),
        { expelOverflow: true },
      ),
    );
  });

  it("labels Switch as local topology metadata and saves its editable fields", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <SwitchPropertiesPanel
        visualSwitch={visualSwitch()}
        onClose={vi.fn()}
        onSave={onSave}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByText(/never written to SDEX/i)).toBeVisible();
    const name = screen.getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Updated switch");
    await user.click(screen.getByRole("button", { name: "Save Switch" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        "switch-1",
        expect.objectContaining({ name: "Updated switch" }),
      ),
    );
  });

  it("requires an explicit routing policy before deleting a Switch", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <SwitchPropertiesPanel
        visualSwitch={visualSwitch()}
        onClose={vi.fn()}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Delete Switch" }));
    expect(
      screen.getByRole("button", { name: "Delete and reconnect" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Leave without visual route" }),
    ).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "Leave without visual route" }),
    );
    await waitFor(() =>
      expect(onDelete).toHaveBeenCalledWith("switch-1", {
        leaveUnrouted: true,
      }),
    );
  });
});

describe("SDEX canvas information boundary", () => {
  it("omits hostname and FQDN from the node but keeps them in details", () => {
    const gateway = makeGateway({
      address: "gateway-address",
      host: "gateway-host",
      metadata: {
        product_type: "SDEX Suite",
        fqdn: "sdex-edge.example.local",
        hostname: "sdex-edge-host",
        os: "Linux",
        arch: "aarch64",
      },
    });
    const gatewayProps = baseNodeProps<GatewayFlowNode>(gateway.id, "gateway", {
      connection: gateway,
      networkInterfaces: [],
      onOpen: vi.fn(),
    });

    const { container, unmount } = render(<GatewayNodeCard {...gatewayProps} />);
    expect(container).not.toHaveTextContent("gateway-address");
    expect(container).not.toHaveTextContent("gateway-host");
    expect(container).not.toHaveTextContent("sdex-edge.example.local");
    expect(container).not.toHaveTextContent("sdex-edge-host");
    unmount();

    render(<DetailsDrawer node={gateway} onClose={vi.fn()} />);
    expect(screen.getByText("sdex-edge.example.local")).toBeVisible();
    expect(screen.getByText("sdex-edge-host")).toBeVisible();
  });
});
