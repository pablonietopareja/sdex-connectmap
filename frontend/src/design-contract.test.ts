import { describe, expect, it } from "vitest";
import indexHtml from "../index.html?raw";
import styles from "./styles/index.css?raw";

describe("static visual contract", () => {
  it("ships the official SVG favicon and product title", () => {
    expect(indexHtml).toContain(
      '<link rel="icon" type="image/svg+xml" href="/icons/SDEX_ConnectMap_logo.svg" />',
    );
    expect(indexHtml).toContain("<title>SDEX ConnectMap</title>");
    expect(indexHtml).not.toContain("by Pablo");
  });

  it("keeps the exact doubled cable widths in central tokens", () => {
    expect(styles).toMatch(/--edge-sheath-width:\s*11px;/);
    expect(styles).toMatch(/--edge-flow-width:\s*5\.6px;/);
    expect(styles).toMatch(/--edge-hit-width:\s*28px;/);
    expect(styles).toContain("stroke-width: var(--edge-sheath-width)");
    expect(styles).toContain("stroke-width: var(--edge-flow-width)");
  });

  it("supports forward and per-edge reverse dash animation", () => {
    expect(styles).toMatch(
      /@keyframes data-flow[\s\S]*stroke-dashoffset:\s*-0\.073;/,
    );
    expect(styles).toMatch(
      /\.edge-data-flow-reverse\s*\{[\s\S]*animation-direction:\s*reverse;/,
    );
  });

  it("uses the exact requested light canvas and dot colors", () => {
    expect(styles).toMatch(/:root\s*\{[\s\S]*--canvas-bg:\s*#dfdfdf;/);
    expect(styles).toMatch(/:root\s*\{[\s\S]*--canvas-dot:\s*#b6bac6;/);
    expect(styles).toMatch(/--canvas-dot-opacity:\s*1;/);
  });

  it("defines themed dropdown surfaces and reduced-motion behavior", () => {
    expect(styles).toMatch(/:root\s*\{[\s\S]*--dropdown-bg:/);
    expect(styles).toMatch(
      /:root\[data-theme="dark"\]\s*\{[\s\S]*--dropdown-bg:/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.edge-data-flow\s*\{[\s\S]*animation:\s*none;/,
    );
  });

  it("reserves a prominent contained icon area in the details drawer", () => {
    expect(styles).toMatch(/\.details-icon\s*\{[\s\S]*width:\s*104px;/);
    expect(styles).toMatch(/\.details-icon\s*\{[\s\S]*height:\s*104px;/);
    expect(styles).toMatch(
      /\.details-icon img\s*\{[\s\S]*object-fit:\s*contain;/,
    );
  });

  it("keeps the editor toolbar beside the summary on desktop and above canvas controls on mobile", () => {
    expect(styles).toMatch(
      /\.editor-toolbar\s*\{[\s\S]*?top:\s*18px;[\s\S]*?left:\s*292px;/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 720px\)\s*\{[\s\S]*?\.editor-toolbar\s*\{[\s\S]*?right:\s*10px;[\s\S]*?bottom:\s*66px;[\s\S]*?left:\s*auto;/,
    );
  });
});
