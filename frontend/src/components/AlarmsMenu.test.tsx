import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import styles from "../styles/index.css?raw";
import type { TopologyAlarm } from "../types";
import { AlarmsMenu } from "./AlarmsMenu";

function makeAlarm(
  id: string,
  overrides: Partial<TopologyAlarm> = {},
): TopologyAlarm {
  return {
    id,
    severity: "warning",
    title: `Alarm ${id}`,
    description: `Description for ${id}`,
    ...overrides,
  };
}

describe("AlarmsMenu", () => {
  it("shows a unique active count and the complete alarm list", async () => {
    const user = userEvent.setup();
    render(
      <AlarmsMenu
        alarms={[
          makeAlarm("partial_discovery", {
            title: "Discovery is partial",
            source: "discovery",
          }),
          makeAlarm("partial_discovery", {
            title: "Discovery is partial",
          }),
          makeAlarm("sdex_unreachable", {
            severity: "error",
            title: "SDEX is unavailable",
          }),
          makeAlarm("informational", { severity: "info" }),
        ]}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Alarms, 3 active" });
    expect(trigger).toHaveTextContent("Alarms3");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("dialog", { name: "Active alarms" })).toBeVisible();
    expect(screen.getByRole("list", { name: "Active alarms" })).toBeVisible();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("Discovery is partial")).toBeVisible();
    expect(screen.getByText("Source: discovery")).toBeVisible();
    expect(screen.getByText("Error")).toBeVisible();
    expect(screen.getByText("Information")).toBeVisible();
  });

  it("focuses the first alarm, supports arrow navigation, and restores focus on Escape", async () => {
    const user = userEvent.setup();
    render(
      <AlarmsMenu alarms={[makeAlarm("one"), makeAlarm("two")]} />,
    );

    const trigger = screen.getByRole("button", { name: "Alarms, 2 active" });
    await user.click(trigger);
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(items[1]).toHaveFocus();
    await user.keyboard("{Home}");
    expect(items[0]).toHaveFocus();
    await user.keyboard("{End}");
    expect(items[1]).toHaveFocus();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("opens from the keyboard and closes after a pointer press outside", async () => {
    const user = userEvent.setup();
    render(
      <main>
        <AlarmsMenu alarms={[makeAlarm("one")]} />
        <button type="button">Outside</button>
      </main>,
    );

    const trigger = screen.getByRole("button", { name: "Alarms, 1 active" });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("dialog")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps Alarms 0 visible and provides a useful empty state", async () => {
    const user = userEvent.setup();
    render(<AlarmsMenu alarms={[]} />);

    const trigger = screen.getByRole("button", { name: "Alarms, 0 active" });
    expect(trigger).toHaveTextContent("Alarms0");
    await user.click(trigger);
    expect(screen.getByText("No active alarms.")).toBeVisible();
  });

  it("renders many alarms in the dedicated scroll region", async () => {
    const user = userEvent.setup();
    render(
      <AlarmsMenu
        alarms={Array.from({ length: 40 }, (_, index) =>
          makeAlarm(`alarm-${index}`),
        )}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Alarms, 40 active" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(40);
    expect(document.querySelector(".alarms-menu-scroll")).toBeVisible();
  });

  it("uses shared light/dark tokens and viewport-bounded responsive CSS", () => {
    expect(styles).toMatch(
      /\.alarms-menu-popover\s*\{[\s\S]*?color:\s*var\(--dropdown-text\);[\s\S]*?background:\s*var\(--dropdown-bg\);/,
    );
    expect(styles).toMatch(
      /\.alarms-menu-scroll\s*\{[\s\S]*?overflow-y:\s*auto;/,
    );
    expect(styles).toMatch(
      /\.alarms-menu-popover\s*\{[\s\S]*?max-height:\s*min\(420px, calc\(100vh - var\(--topbar-height\) - 16px\)\);/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 620px\)\s*\{[\s\S]*?\.alarms-menu-popover\s*\{[\s\S]*?width:\s*calc\(100vw - 16px\);/,
    );

    document.documentElement.dataset.theme = "dark";
    const { rerender } = render(<AlarmsMenu alarms={[makeAlarm("dark")]} />);
    expect(screen.getByRole("button", { name: "Alarms, 1 active" })).toBeVisible();
    document.documentElement.dataset.theme = "light";
    rerender(<AlarmsMenu alarms={[makeAlarm("light")]} />);
    expect(screen.getByRole("button", { name: "Alarms, 1 active" })).toBeVisible();
    delete document.documentElement.dataset.theme;
  });
});
