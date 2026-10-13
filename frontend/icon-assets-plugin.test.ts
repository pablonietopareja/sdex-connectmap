import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ICON_FILENAMES } from "./icon-assets-plugin";

const iconsDirectory = resolve(process.cwd(), "../icons");

describe("canonical icon registry", () => {
  it("contains every canonical SVG and no stale filename", () => {
    const canonicalFiles = readdirSync(iconsDirectory)
      .filter((filename) => filename.toLowerCase().endsWith(".svg"))
      .sort();

    expect([...ICON_FILENAMES].sort()).toEqual(canonicalFiles);
    for (const filename of ICON_FILENAMES) {
      expect(readFileSync(resolve(iconsDirectory, filename), "utf8")).toContain(
        "<svg",
      );
    }
  });

  it("backs every registered UI icon path with a canonical asset", () => {
    const allowed = new Set<string>(ICON_FILENAMES);
    const registrySources = [
      "src/constants.ts",
      "src/components/editor/EditorToolbar.tsx",
      "src/components/nodes/SwitchNodeCard.tsx",
      "src/components/Onboarding.tsx",
      "src/components/TopBar.tsx",
      "index.html",
    ].map((relativePath) =>
      readFileSync(resolve(process.cwd(), relativePath), "utf8"),
    );
    const uiPaths = registrySources.flatMap(
      (source) => source.match(/\/icons\/[A-Za-z0-9_.-]+\.svg/g) ?? [],
    );

    expect(uiPaths.length).toBeGreaterThan(0);
    for (const iconPath of uiPaths) {
      expect(iconPath.startsWith("/icons/")).toBe(true);
      expect(allowed.has(iconPath.slice("/icons/".length))).toBe(true);
    }
  });
});
