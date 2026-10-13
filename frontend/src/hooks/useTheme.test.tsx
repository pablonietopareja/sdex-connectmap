import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useTheme } from "./useTheme";

function ThemeHarness() {
  const { preference, resolvedTheme, setPreference } = useTheme();
  return (
    <div>
      <span>{preference}</span>
      <span>{resolvedTheme}</span>
      <button type="button" onClick={() => setPreference("dark")}>
        Use dark
      </button>
    </div>
  );
}

describe("useTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("applies and persists the selected theme", async () => {
    const user = userEvent.setup();
    render(<ThemeHarness />);
    await user.click(screen.getByRole("button", { name: "Use dark" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(localStorage.getItem("connectmap.theme")).toBe("dark");
  });
});
