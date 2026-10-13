import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { EdgeVisualStyle } from "../types";
import { EdgeStylePanel } from "./EdgeStylePanel";
import { hexToHsv, hsvToHex, normalizeHexColor } from "./edges/color";

const CUSTOM_STYLE: EdgeVisualStyle = {
  edge_id: "sdex-to-modbus:line-1",
  sheath_color: "#123456",
  flow_color: "#ABCDEF",
  reverse_flow: false,
  updated_at: "2026-07-29T10:00:00Z",
  schema_version: 1,
};

describe("edge color helpers", () => {
  it("accepts only six-digit hexadecimal colors and normalizes uppercase", () => {
    expect(normalizeHexColor("12ab34")).toBe("#12AB34");
    expect(normalizeHexColor("#abcdef")).toBe("#ABCDEF");
    expect(normalizeHexColor("url(javascript:alert(1))")).toBeNull();
    expect(normalizeHexColor("#123")).toBeNull();
  });

  it("round-trips representative HSV colors", () => {
    expect(hsvToHex(hexToHsv("#4DA3FF"))).toBe("#4DA3FF");
    expect(hsvToHex({ hue: 120, saturation: 100, value: 100 })).toBe(
      "#00FF00",
    );
  });
});

describe("EdgeStylePanel", () => {
  it("offers both keyboard-navigable tabs, palette, SV area and hue control", async () => {
    const user = userEvent.setup();
    render(
      <EdgeStylePanel
        edgeId="sdex-to-modbus:line-1"
        style={null}
        onClose={vi.fn()}
        onApply={vi.fn()}
        onReset={vi.fn()}
      />,
    );

    const cableTab = screen.getByRole("tab", { name: "Cable" });
    const flowTab = screen.getByRole("tab", { name: "Data flow" });
    expect(cableTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("button", { name: /Set cable color/i })).toHaveLength(
      13,
    );
    expect(
      screen.getByRole("slider", {
        name: "Cable color saturation and brightness",
      }),
    ).toBeVisible();
    expect(screen.getByRole("slider", { name: "Cable color hue" })).toBeVisible();
    expect(
      screen.queryByRole("switch", { name: "Reverse Flow" }),
    ).not.toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Cable appearance" })).toHaveFocus(),
    );
    cableTab.focus();
    await user.keyboard("{ArrowRight}");
    expect(flowTab).toHaveFocus();
    expect(flowTab).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("slider", {
        name: "Data flow color saturation and brightness",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("switch", { name: "Reverse Flow" }),
    ).not.toBeChecked();
  });

  it("rejects arbitrary input and applies normalized #RRGGBB values", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn().mockResolvedValue({
      ...CUSTOM_STYLE,
      sheath_color: "#12AB34",
      flow_color: "#4DA3FF",
    });
    render(
      <EdgeStylePanel
        edgeId={CUSTOM_STYLE.edge_id}
        style={null}
        onClose={vi.fn()}
        onApply={onApply}
        onReset={vi.fn()}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Hex color" });
    const apply = screen.getByRole("button", { name: "Apply" });
    await user.clear(input);
    await user.type(input, "url(red)");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(apply).toBeDisabled();
    expect(onApply).not.toHaveBeenCalled();

    await user.clear(input);
    await user.type(input, "12ab34");
    expect(input).toHaveAttribute("aria-invalid", "false");
    await user.click(apply);
    expect(onApply).toHaveBeenCalledWith(CUSTOM_STYLE.edge_id, {
      sheath_color: "#12AB34",
      flow_color: "#4DA3FF",
      reverse_flow: false,
    });
  });

  it("saves Reverse Flow per cable and restores its persisted state", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn().mockResolvedValue({
      ...CUSTOM_STYLE,
      reverse_flow: true,
    });
    const props = {
      edgeId: CUSTOM_STYLE.edge_id,
      onClose: vi.fn(),
      onApply,
      onReset: vi.fn(),
    };
    const { rerender } = render(
      <EdgeStylePanel
        {...props}
        style={null}
      />,
    );

    await user.click(screen.getByRole("tab", { name: "Data flow" }));
    const reverseFlow = screen.getByRole("switch", { name: "Reverse Flow" });
    expect(reverseFlow).not.toBeChecked();
    await user.click(reverseFlow);
    expect(reverseFlow).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApply).toHaveBeenCalledWith(CUSTOM_STYLE.edge_id, {
      sheath_color: "#5A7FAE",
      flow_color: "#4DA3FF",
      reverse_flow: true,
    });

    rerender(
      <EdgeStylePanel
        {...props}
        style={{ ...CUSTOM_STYLE, reverse_flow: true }}
      />,
    );
    expect(
      screen.getByRole("switch", { name: "Reverse Flow" }),
    ).toBeChecked();
  });

  it("resets persisted customization and closes with Escape", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <EdgeStylePanel
        edgeId={CUSTOM_STYLE.edge_id}
        style={CUSTOM_STYLE}
        onClose={onClose}
        onApply={vi.fn()}
        onReset={onReset}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(onReset).toHaveBeenCalledWith(CUSTOM_STYLE.edge_id);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("resets only the persisted route from the dedicated Route tab", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    const onResetRoute = vi.fn().mockResolvedValue(undefined);
    render(
      <EdgeStylePanel
        edgeId={CUSTOM_STYLE.edge_id}
        style={CUSTOM_STYLE}
        route={{
          edge_id: CUSTOM_STYLE.edge_id,
          routing_mode: "orthogonal",
          waypoints: [
            { id: "corner:1", x: 100, y: 200, kind: "corner", order: 0 },
          ],
          updated_at: "2026-07-31T10:00:00Z",
          schema_version: 1,
        }}
        onClose={vi.fn()}
        onApply={vi.fn()}
        onReset={onReset}
        onResetRoute={onResetRoute}
      />,
    );

    await user.click(screen.getByRole("tab", { name: "Route" }));
    expect(screen.getByText("orthogonal")).toBeVisible();
    expect(screen.getByText("1", { selector: "dd" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Reset route" }));
    expect(onResetRoute).toHaveBeenCalledWith(CUSTOM_STYLE.edge_id);
    expect(onReset).not.toHaveBeenCalled();
  });

  it("requires confirmation before removing an individual visual link", async () => {
    const user = userEvent.setup();
    const onDeleteVisualLink = vi.fn().mockResolvedValue(undefined);
    render(
      <EdgeStylePanel
        edgeId="visual-link:switch-to-device"
        style={null}
        visualLink
        onClose={vi.fn()}
        onApply={vi.fn()}
        onReset={vi.fn()}
        onDeleteVisualLink={onDeleteVisualLink}
      />,
    );

    await user.click(screen.getByRole("tab", { name: "Route" }));
    await user.click(screen.getByRole("button", { name: "Remove visual link" }));
    expect(onDeleteVisualLink).not.toHaveBeenCalled();
    expect(screen.getByText("Remove this visual link?")).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "Confirm remove link" }),
    );
    expect(onDeleteVisualLink).toHaveBeenCalledOnce();
    expect(onDeleteVisualLink).toHaveBeenCalledWith(
      "visual-link:switch-to-device",
    );
  });
});
