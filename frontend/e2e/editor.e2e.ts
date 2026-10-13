import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const screenshotDirectory = fileURLToPath(
  new URL("../test-artifacts/editor/", import.meta.url),
);

const editableEdgeId = "visual-link:00000000-0000-4000-8000-000000000011";

async function fitTopology(page: Page) {
  await page.getByRole("button", { name: "Fit topology" }).click();
  await page.locator(".react-flow__viewport").evaluate(async (element) => {
    let previous = element.getAttribute("style");
    let stableFrames = 0;
    while (stableFrames < 3) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const current = element.getAttribute("style");
      stableFrames = current === previous ? stableFrames + 1 : 0;
      previous = current;
    }
  });
}

async function chooseTheme(page: Page, theme: "Light" | "Dark") {
  await page.getByRole("combobox", { name: "Theme" }).click();
  await page.getByRole("option", { name: theme, exact: true }).click();
}

async function enableEditor(page: Page) {
  const editorSwitch = page.getByRole("switch", { name: "Editor" });
  await expect(editorSwitch).not.toBeChecked();
  await page.getByText("Editor", { exact: true }).click();
  await expect(editorSwitch).toBeChecked();
}

async function pointOnPath(
  path: Locator,
  fraction = 0.5,
): Promise<{ x: number; y: number }> {
  let result: { x: number; y: number } | null = null;
  await expect
    .poll(async () => {
      result = await path.evaluate(async (element, requestedFraction) => {
        if (!(element instanceof SVGPathElement)) {
          throw new Error("Expected an SVG path for cable interaction.");
        }
        // Raw mouse coordinates do not get Playwright's actionability checks.
        // A point measured during Fit topology can miss by click time.
        const geometry = () => {
          const matrix = element.getScreenCTM();
          if (!matrix) throw new Error("The cable path has no screen transform.");
          return JSON.stringify([
            element.getAttribute("d"),
            matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f,
          ]);
        };
        let previous = geometry();
        let stableFrames = 0;
        while (stableFrames < 3) {
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
          // React Flow can replace an edge while measuring newly rendered nodes.
          // Retry the locator instead of measuring a detached path.
          if (!element.isConnected) return null;
          const current = geometry();
          stableFrames = current === previous ? stableFrames + 1 : 0;
          previous = current;
        }
        const matrix = element.getScreenCTM();
        if (!matrix) throw new Error("The cable path has no screen transform.");
        const length = element.getTotalLength();
        const candidates = Array.from(
          { length: 81 },
          (_, index) => 0.1 + index * 0.01,
        ).sort(
          (left, right) =>
            Math.abs(left - requestedFraction) -
            Math.abs(right - requestedFraction),
        );
        for (const candidate of candidates) {
          const point = element.getPointAtLength(length * candidate);
          const x = matrix.a * point.x + matrix.c * point.y + matrix.e;
          const y = matrix.b * point.x + matrix.d * point.y + matrix.f;
          if (document.elementFromPoint(x, y) === element) return { x, y };
        }
        return null;
      }, fraction);
      return result;
    }, { message: "The cable path has a stable, visible interaction point." })
    .not.toBeNull();
  if (!result) throw new Error("No targetable point was found on the cable path.");
  return result;
}

test("selecting a persisted cable after an animated fit reveals its saved waypoint", async ({
  page,
}) => {
  const routeWrites: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() !== "GET" &&
      new URL(request.url()).pathname.endsWith("/route")
    ) {
      routeWrites.push(`${request.method()} ${request.url()}`);
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("rack-node")).toHaveCount(1);
  const before = await page.request.get("/api/topology");
  expect(before.ok()).toBe(true);
  const initialTopology = await before.json();
  const savedRoute = initialTopology.visual_topology.routes[editableEdgeId];
  expect(savedRoute.routing_mode).toBe("manual");
  expect(savedRoute.waypoints).toHaveLength(1);

  await enableEditor(page);
  await page.getByRole("button", { name: "Zoom in" }).click();
  // Start the 450 ms fit and immediately ask for a targetable path point.
  // This exercises the coordinate helper while the viewport is still moving.
  await page.getByRole("button", { name: "Fit topology" }).click();
  const hit = page.getByTestId(`edge-route-hit-${editableEdgeId}`);
  const point = await pointOnPath(hit, 0.35);
  await page.mouse.click(point.x, point.y);
  await expect(hit.locator("..")).toHaveClass(/\bselected\b/);
  await expect(page.locator(".edge-waypoint")).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "Cable waypoint 1 of 1" }),
  ).toBeVisible();

  const after = await page.request.get("/api/topology");
  expect(after.ok()).toBe(true);
  const selectedTopology = await after.json();
  expect(selectedTopology.visual_topology.routes[editableEdgeId]).toEqual(savedRoute);
  expect(selectedTopology.nodes.map((node: { id: string }) => node.id)).toEqual(
    initialTopology.nodes.map((node: { id: string }) => node.id),
  );
  expect(routeWrites).toEqual([]);
});

async function dragFromLocatorToPoint(
  page: Page,
  source: Locator,
  target: { x: number; y: number },
) {
  const bounds = await source.boundingBox();
  if (!bounds) throw new Error("The drag source has no visible bounds.");
  await page.mouse.move(
    bounds.x + bounds.width / 2,
    bounds.y + bounds.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(target.x, target.y, { steps: 24 });
  await page.waitForTimeout(100);
  await page.mouse.up();
}

async function dragHandleToHandle(
  page: Page,
  sourceHandle: Locator,
  targetHandle: Locator,
) {
  await expect(sourceHandle).toBeVisible();
  await expect(targetHandle).toBeVisible();
  // Playwright waits for stable, unobstructed handles before measuring them.
  // Fit topology animates the viewport, so a fixed delay can leave stale coordinates.
  await sourceHandle.hover();
  await targetHandle.hover();
  const sourceBounds = await sourceHandle.boundingBox();
  const targetBounds = await targetHandle.boundingBox();
  if (!sourceBounds || !targetBounds) {
    throw new Error("A React Flow connection handle has no visible bounds.");
  }
  await page.mouse.move(
    sourceBounds.x + sourceBounds.width / 2,
    sourceBounds.y + sourceBounds.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    targetBounds.x + targetBounds.width / 2,
    targetBounds.y + targetBounds.height / 2,
    { steps: 24 },
  );
  await page.waitForTimeout(100);
  await page.mouse.up();
}

async function saveRackDimensions(
  page: Page,
  rack: Locator,
  rows: number,
  columns: number,
) {
  await rack.locator(".rack-node-header").dblclick();
  const panel = page.getByTestId("rack-properties-panel");
  await expect(panel).toBeVisible();
  await panel.getByLabel("Rows").fill(String(rows));
  await panel.getByLabel("Columns").fill(String(columns));
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      new URL(response.url()).pathname.startsWith("/api/visual-elements/"),
  );
  await panel.getByRole("button", { name: "Save Rack" }).click();
  expect((await responsePromise).ok()).toBe(true);
  await page.getByRole("button", { name: "Close Rack properties" }).click();
}

test("advanced Editor topology persists without mutating source connections", async ({
  page,
}) => {
  mkdirSync(screenshotDirectory, { recursive: true });
  const consoleErrors: string[] = [];
  const failedResponses: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/");
  await expect(page.getByTestId("rack-node")).toHaveCount(1);
  await expect(page.getByTestId("switch-node")).toHaveCount(1);
  await expect(page.locator('[data-variant="embedded"]')).toHaveCount(2);
  await expect(page.locator(".rack-slot-empty")).toHaveCount(1);
  await expect(page.locator(".editor-toolbar")).toHaveCount(0);
  await expect(
    page.locator('.data-cable-edge[data-routing-mode="manual"]'),
  ).toHaveCount(1);
  await expect(
    page.locator('.data-cable-edge[data-routing-mode="orthogonal"]'),
  ).toHaveCount(1);
  await expect(page.locator('.switch-node-card img[src="/icons/Switch.svg"]')).toHaveCount(1);
  await expect(page.locator(".switch-node-card .react-flow__handle-top")).toHaveCount(0);
  await expect(page.locator(".switch-node-card .react-flow__handle-bottom")).toHaveCount(0);

  const sourceTopology = await page.request.get("/api/topology");
  expect(sourceTopology.ok()).toBe(true);
  const sourcePayload = (await sourceTopology.json()) as {
    nodes: unknown[];
    summary: { total_configured: number };
    visual_topology: {
      elements: unknown[];
      rack_memberships: unknown[];
      routes: Record<
        string,
        { routing_mode: "manual" | "orthogonal"; waypoints: unknown[] }
      >;
    };
  };
  expect(sourcePayload.nodes).toHaveLength(8);
  expect(sourcePayload.summary.total_configured).toBe(8);
  expect(sourcePayload.visual_topology.elements).toHaveLength(2);
  expect(sourcePayload.visual_topology.rack_memberships).toHaveLength(2);
  expect(
    Object.values(sourcePayload.visual_topology.routes)
      .map((route) => route.routing_mode)
      .sort(),
  ).toEqual(["manual", "orthogonal"]);

  const gateway = page.getByTestId("gateway-node");
  await expect(gateway).not.toContainText("sdex-edgenode.local");
  await expect(gateway).not.toContainText("sdex-edgenode");
  await gateway.dblclick();
  const details = page.getByTestId("details-drawer");
  await expect(details).toContainText("sdex-edgenode.local");
  await expect(details).toContainText("sdex-edgenode");
  await page.getByRole("button", { name: "Close details" }).click();

  await enableEditor(page);
  await expect(page.getByTestId("editor-toolbar")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add Rack" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add Switch" })).toBeVisible();
  await expect(page.locator(".switch-node-card .react-flow__handle-left")).not.toHaveCount(0);
  await expect(page.locator(".switch-node-card .react-flow__handle-right")).not.toHaveCount(0);
  await fitTopology(page);

  const productionRack = page
    .getByTestId("rack-node")
    .filter({ hasText: "Production Rack" });
  const rackBounds = await productionRack.boundingBox();
  const canvasBounds = await page.locator(".topology-canvas").boundingBox();
  if (!rackBounds || !canvasBounds) {
    throw new Error("Rack or canvas bounds are unavailable for membership drag.");
  }
  const ejectedMemberId = "siemens_s7_1200_1500:packaging-plc";
  const ejectedMember = page.getByTestId(`rf__node-${ejectedMemberId}`);
  const removeMembershipResponse = page.waitForResponse((response) => {
    const path = new URL(response.url()).pathname;
    return (
      response.request().method() === "DELETE" &&
      path.startsWith("/api/racks/") &&
      path.includes("/members/")
    );
  });
  const ejectionPoint = {
    x: Math.min(
      canvasBounds.x + canvasBounds.width - 180,
      rackBounds.x + rackBounds.width + 180,
    ),
    y: rackBounds.y + rackBounds.height / 2,
  };
  expect(ejectionPoint.x).toBeGreaterThan(rackBounds.x + rackBounds.width);
  await dragFromLocatorToPoint(
    page,
    ejectedMember.locator(".node-header"),
    ejectionPoint,
  );
  expect((await removeMembershipResponse).ok()).toBe(true);
  await expect(page.locator('[data-variant="embedded"]')).toHaveCount(1);
  await expect(productionRack.locator(".rack-slot-empty")).toHaveCount(2);
  const topologyAfterEject = await page.request.get("/api/topology");
  const ejectedPayload = (await topologyAfterEject.json()) as {
    nodes: unknown[];
    visual_topology: { rack_memberships: unknown[] };
  };
  expect(ejectedPayload.nodes).toHaveLength(8);
  expect(ejectedPayload.visual_topology.rack_memberships).toHaveLength(1);

  const vacatedSlot = productionRack.locator(
    '.rack-slot-empty[data-row="0"][data-column="0"]',
  );
  const slotBounds = await vacatedSlot.boundingBox();
  if (!slotBounds) throw new Error("The vacated Rack slot has no visible bounds.");
  const addMembershipResponse = page.waitForResponse((response) => {
    const path = new URL(response.url()).pathname;
    return (
      response.request().method() === "PUT" &&
      path.startsWith("/api/racks/") &&
      path.endsWith("/members")
    );
  });
  await dragFromLocatorToPoint(
    page,
    ejectedMember.locator(".node-header"),
    {
      x: slotBounds.x + slotBounds.width / 2,
      y: slotBounds.y + slotBounds.height / 2,
    },
  );
  expect((await addMembershipResponse).ok()).toBe(true);
  await expect(page.locator('[data-variant="embedded"]')).toHaveCount(2);
  await expect(productionRack.locator(".rack-slot-empty")).toHaveCount(1);
  const topologyAfterReturn = await page.request.get("/api/topology");
  const returnedPayload = (await topologyAfterReturn.json()) as {
    nodes: unknown[];
    visual_topology: { rack_memberships: unknown[] };
  };
  expect(returnedPayload.nodes).toHaveLength(8);
  expect(returnedPayload.visual_topology.rack_memberships).toHaveLength(2);

  const createSwitchResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/visual-elements",
  );
  await page.getByRole("button", { name: "Add Switch" }).dragTo(
    page.locator(".topology-canvas"),
    {
      targetPosition: {
        x: canvasBounds.width * 0.68,
        y: canvasBounds.height * 0.82,
      },
    },
  );
  expect((await createSwitchResponse).ok()).toBe(true);
  const switchPanel = page.getByTestId("switch-properties-panel");
  await expect(switchPanel).toBeVisible();
  await expect(switchPanel.getByLabel("Name")).toHaveValue("New Switch");
  await expect(page.getByTestId("switch-node")).toHaveCount(2);
  await page.getByRole("button", { name: "Close Switch properties" }).click();
  const newSwitch = page
    .getByTestId("switch-node")
    .filter({ hasText: "New Switch" });
  await expect(newSwitch).toHaveCount(1);
  await fitTopology(page);

  const energyMeter = page
    .getByTestId("connection-node-modbus")
    .filter({ hasText: "Energy Meter" });
  const deviceToSwitchResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/visual-links",
  );
  await dragHandleToHandle(
    page,
    energyMeter.locator(
      '.react-flow__handle-right[data-handleid="right"]',
    ),
    newSwitch.locator(
      '.react-flow__handle-left[data-handleid="left:new"]',
    ),
  );
  const deviceToSwitch = await deviceToSwitchResponse;
  expect(deviceToSwitch.ok()).toBe(true);
  const deviceToSwitchLink = (await deviceToSwitch.json()) as {
    id: string;
    source: string;
    target: string;
    external_interface: string;
  };
  expect(deviceToSwitchLink.source).toContain("modbus");
  expect(deviceToSwitchLink.target).toContain("switch:");
  expect(deviceToSwitchLink.external_interface).toBe("eth1");

  const switchToSdexResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/visual-links",
  );
  await dragHandleToHandle(
    page,
    newSwitch.locator(
      '.react-flow__handle-right[data-handleid="right:new"]',
    ),
    gateway.locator(
      '.react-flow__handle-top[data-handleid="sdex-eth1"]',
    ),
  );
  const switchToSdex = await switchToSdexResponse;
  expect(switchToSdex.ok()).toBe(true);
  const switchToSdexLink = (await switchToSdex.json()) as {
    id: string;
    source: string;
    target: string;
    external_interface: string;
  };
  expect(switchToSdexLink.source).toBe(deviceToSwitchLink.target);
  expect(switchToSdexLink.external_interface).toBe("eth1");
  await expect(newSwitch.locator(".react-flow__handle-left")).not.toHaveCount(0);
  await expect(newSwitch.locator(".react-flow__handle-right")).not.toHaveCount(0);
  await expect(newSwitch.locator(".react-flow__handle-top")).toHaveCount(0);
  await expect(newSwitch.locator(".react-flow__handle-bottom")).toHaveCount(0);

  const topologyThroughSwitch = await page.request.get("/api/topology");
  expect(topologyThroughSwitch.ok()).toBe(true);
  const switchedPayload = (await topologyThroughSwitch.json()) as {
    nodes: unknown[];
    visual_topology: {
      links: Array<{ id: string; source: string; target: string }>;
    };
  };
  expect(switchedPayload.nodes).toHaveLength(8);
  expect(
    switchedPayload.visual_topology.links.map((link) => link.id),
  ).toEqual(
    expect.arrayContaining([deviceToSwitchLink.id, switchToSdexLink.id]),
  );

  await newSwitch.focus();
  await newSwitch.press("Enter");
  await expect(switchPanel).toBeVisible();
  await switchPanel.getByRole("button", { name: "Delete Switch" }).click();
  const deleteSwitchResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "DELETE" &&
      new URL(response.url()).pathname.startsWith("/api/visual-elements/"),
  );
  await switchPanel
    .locator(".inline-confirm-actions")
    .getByRole("button", { name: "Delete and reconnect" })
    .click();
  expect((await deleteSwitchResponse).ok()).toBe(true);
  await expect(newSwitch).toHaveCount(0);
  await expect(page.getByTestId("switch-node")).toHaveCount(1);
  await expect(page.getByTestId("switch-node")).toContainText("Line Switch");
  const topologyAfterSwitchDelete = await page.request.get("/api/topology");
  expect(topologyAfterSwitchDelete.ok()).toBe(true);
  const restoredSwitchPayload = (await topologyAfterSwitchDelete.json()) as {
    nodes: unknown[];
    visual_topology: { links: Array<{ id: string }> };
  };
  expect(restoredSwitchPayload.nodes).toHaveLength(8);
  expect(
    restoredSwitchPayload.visual_topology.links.some(
      (link) =>
        link.id === deviceToSwitchLink.id || link.id === switchToSdexLink.id,
    ),
  ).toBe(false);
  await fitTopology(page);
  const editableHit = page.getByTestId(`edge-route-hit-${editableEdgeId}`);
  const selectionPoint = await pointOnPath(editableHit, 0.35);
  expect(selectionPoint.x).toBeGreaterThan(0);
  expect(selectionPoint.x).toBeLessThan(1920);
  expect(selectionPoint.y).toBeGreaterThan(70);
  expect(selectionPoint.y).toBeLessThan(1080);
  await page.mouse.click(selectionPoint.x, selectionPoint.y);
  await expect(editableHit.locator("..")).toHaveClass(/\bselected\b/);
  await expect(page.locator(".edge-waypoint")).toHaveCount(1);
  const saveResponse = page.waitForResponse(
    (response) =>
      response.url().includes(encodeURIComponent(editableEdgeId)) &&
      response.request().method() === "PUT" &&
      response.url().endsWith("/route"),
  );
  const bendPoint = await pointOnPath(editableHit, 0.62);
  await page.keyboard.down("Control");
  try {
    await page.mouse.click(bendPoint.x, bendPoint.y);
  } finally {
    await page.keyboard.up("Control");
  }
  expect((await saveResponse).ok()).toBe(true);
  await expect(page.locator(".edge-waypoint")).toHaveCount(2);
  await expect(
    page.locator('.data-cable-edge[data-routing-mode="orthogonal"]'),
  ).toHaveCount(2);
  await expect(editableHit).toHaveAttribute("d", /^M [^C]+(?: L [^C]+)+$/);

  await chooseTheme(page, "Dark");
  await fitTopology(page);
  await page.screenshot({
    path: `${screenshotDirectory}/01-overview-dark.png`,
    fullPage: true,
  });
  await page.getByTestId("editor-toolbar").screenshot({
    path: `${screenshotDirectory}/02-toolbar.png`,
  });
  await page.getByTestId("rack-node").screenshot({
    path: `${screenshotDirectory}/03-rack-members.png`,
  });
  await page.getByTestId("switch-node").screenshot({
    path: `${screenshotDirectory}/04-switch.png`,
  });
  const cableEditorParts = [
    editableHit,
    page.locator(".edge-route-toolbar"),
    ...(await page.locator(".edge-waypoint").all()),
  ];
  const cableEditorBounds: Array<{
    x: number;
    y: number;
    width: number;
    height: number;
  }> = [];
  for (const part of cableEditorParts) {
    const bounds = await part.boundingBox();
    if (bounds) cableEditorBounds.push(bounds);
  }
  const viewport = page.viewportSize();
  if (!viewport || cableEditorBounds.length < 4) {
    throw new Error("Cable, toolbar, or waypoint bounds are unavailable.");
  }
  const margin = 32;
  const clipLeft = Math.max(
    0,
    Math.min(...cableEditorBounds.map(({ x }) => x)) - margin,
  );
  const clipTop = Math.max(
    0,
    Math.min(...cableEditorBounds.map(({ y }) => y)) - margin,
  );
  const clipRight = Math.min(
    viewport.width,
    Math.max(...cableEditorBounds.map(({ x, width }) => x + width)) + margin,
  );
  const clipBottom = Math.min(
    viewport.height,
    Math.max(...cableEditorBounds.map(({ y, height }) => y + height)) + margin,
  );
  await page.screenshot({
    path: `${screenshotDirectory}/05-edge-waypoints.png`,
    clip: {
      x: clipLeft,
      y: clipTop,
      width: clipRight - clipLeft,
      height: clipBottom - clipTop,
    },
  });
  await gateway.screenshot({
    path: `${screenshotDirectory}/06-sdex-compact.png`,
  });

  await page.locator(".topology-canvas").screenshot({
    path: `${screenshotDirectory}/08-edge-90-degree.png`,
  });
  await page
    .getByTestId("connection-node-rockwell_allen_bradley")
    .screenshot({
      path: `${screenshotDirectory}/09-device-typography.png`,
    });

  const createRackResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/visual-elements",
  );
  await page.getByRole("button", { name: "Add Rack" }).click();
  expect((await createRackResponse).ok()).toBe(true);
  const rackPanel = page.getByTestId("rack-properties-panel");
  await expect(rackPanel).toBeVisible();
  await page.getByRole("button", { name: "Close Rack properties" }).click();
  const emptyRack = page.getByTestId("rack-node").filter({ hasText: "New Rack" });
  await expect(emptyRack).toHaveCount(1);
  await expect(emptyRack.locator(".rack-slot-empty")).toHaveCount(3);
  await emptyRack.screenshot({
    path: `${screenshotDirectory}/10-rack-empty.png`,
  });

  await emptyRack.locator(".rack-node-header").dblclick();
  await expect(rackPanel).toBeVisible();
  await rackPanel.getByRole("button", { name: "Delete Rack" }).click();
  const deleteRackResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "DELETE" &&
      new URL(response.url()).pathname.startsWith("/api/visual-elements/"),
  );
  await rackPanel
    .locator(".inline-confirm-actions")
    .getByRole("button", { name: "Delete Rack" })
    .click();
  expect((await deleteRackResponse).ok()).toBe(true);
  await expect(emptyRack).toHaveCount(0);

  await saveRackDimensions(page, productionRack, 2, 2);
  await expect(productionRack.locator(".rack-slot-empty")).toHaveCount(2);
  await expect(productionRack).toContainText("2/4 occupied");
  await saveRackDimensions(page, productionRack, 1, 3);
  await expect(productionRack.locator(".rack-slot-empty")).toHaveCount(1);

  await saveRackDimensions(page, productionRack, 1, 2);
  await expect(productionRack.locator(".rack-slot-empty")).toHaveCount(0);
  await expect(productionRack).toContainText("2/2 occupied");
  await productionRack.screenshot({
    path: `${screenshotDirectory}/11-rack-full.png`,
  });

  await saveRackDimensions(page, productionRack, 1, 3);
  await expect(productionRack.locator(".rack-slot-empty")).toHaveCount(1);

  await chooseTheme(page, "Light");
  await page.screenshot({
    path: `${screenshotDirectory}/07-overview-light.png`,
    fullPage: true,
  });

  await page.reload();
  await enableEditor(page);
  const persistedHit = page.getByTestId(`edge-route-hit-${editableEdgeId}`);
  const persistedPoint = await pointOnPath(persistedHit, 0.35);
  await page.mouse.click(persistedPoint.x, persistedPoint.y);
  await expect(persistedHit.locator("..")).toHaveClass(/\bselected\b/);
  await expect(page.locator(".edge-waypoint")).toHaveCount(2);
  await expect(page.getByTestId("rack-node")).toHaveCount(1);
  await expect(page.getByTestId("switch-node")).toHaveCount(1);

  await chooseTheme(page, "Dark");
  await fitTopology(page);
  await page.locator(".react-flow__pane").click({ position: { x: 1870, y: 40 } });
  await page.screenshot({
    path: `${screenshotDirectory}/12-editor-overview-dark.png`,
    fullPage: true,
  });

  expect(failedResponses).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
