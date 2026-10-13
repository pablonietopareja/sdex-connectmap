import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const screenshotDirectory = fileURLToPath(
  new URL("../test-artifacts/visual/", import.meta.url),
);

async function chooseOption(page: Page, label: string, option: string) {
  const trigger = page.getByRole("combobox", { name: label });
  await trigger.click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

async function screenshotAtIntrinsicSize(
  locator: Locator,
  path: string,
  overflowPadding = 0,
) {
  const previousStyle = await locator.evaluate((element) => {
    const target = element as HTMLElement;
    const renderedWidth = target.getBoundingClientRect().width;
    const scale = renderedWidth / target.offsetWidth;
    const previous = {
      transform: target.style.transform,
      transformOrigin: target.style.transformOrigin,
      zIndex: target.style.zIndex,
    };
    target.style.transform = `scale(${1 / scale})`;
    target.style.transformOrigin = "center";
    target.style.zIndex = "20";
    return previous;
  });
  if (overflowPadding > 0) {
    const box = await locator.boundingBox();
    if (!box) throw new Error("The visual target has no bounding box.");
    await locator.page().screenshot({
      path,
      clip: {
        x: Math.max(0, box.x - overflowPadding),
        y: Math.max(0, box.y - overflowPadding),
        width: box.width + overflowPadding * 2,
        height: box.height + overflowPadding * 2,
      },
    });
  } else {
    await locator.screenshot({ path });
  }
  await locator.evaluate((element, previous) => {
    const target = element as HTMLElement;
    target.style.transform = previous.transform;
    target.style.transformOrigin = previous.transformOrigin;
    target.style.zIndex = previous.zIndex;
  }, previousStyle);
}

async function assertImagesStayInsideShells(page: Page) {
  const violations = await page
    .locator(".node-icon-shell, .gateway-icon-shell")
    .evaluateAll((shells) =>
      shells.flatMap((shell) => {
        const image = shell.querySelector("img");
        if (!image) return ["Missing device image"];
        const shellBox = shell.getBoundingClientRect();
        const imageBox = image.getBoundingClientRect();
        const contained =
          imageBox.left >= shellBox.left - 1 &&
          imageBox.right <= shellBox.right + 1 &&
          imageBox.top >= shellBox.top - 1 &&
          imageBox.bottom <= shellBox.bottom + 1;
        return contained ? [] : ["Device SVG exceeds its visual shell"];
      }),
    );
  expect(violations).toEqual([]);
}

async function assertNodesDoNotOverlap(page: Page) {
  const boxes = await page.locator(".react-flow__node").evaluateAll((nodes) =>
    nodes.map((node) => {
      const box = node.getBoundingClientRect();
      return {
        id: node.getAttribute("data-id"),
        left: box.left,
        top: box.top,
        right: box.right,
        bottom: box.bottom,
      };
    }),
  );
  for (let leftIndex = 0; leftIndex < boxes.length; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < boxes.length;
      rightIndex += 1
    ) {
      const left = boxes[leftIndex];
      const right = boxes[rightIndex];
      if (!left || !right) continue;
      const intersects =
        left.left < right.right &&
        left.right > right.left &&
        left.top < right.bottom &&
        left.bottom > right.top;
      expect(
        intersects,
        `React Flow nodes ${left.id} and ${right.id} overlap`,
      ).toBe(false);
    }
  }
}

async function assertVisualContentStaysInsideCards(page: Page) {
  const violations = await page.locator(".connection-node-card, .gateway-node-card").evaluateAll(
    (cards) =>
      cards.flatMap((card) => {
        const cardBox = card.getBoundingClientRect();
        const cardName =
          card.getAttribute("data-testid") ??
          card.getAttribute("aria-label") ??
          card.className;
        return Array.from(
          card.querySelectorAll(
            ".node-icon-shell img, .gateway-icon-shell img, header strong, .status-badge",
          ),
        ).flatMap((element) => {
          const box = element.getBoundingClientRect();
          const inside =
            box.left >= cardBox.left - 1 &&
            box.right <= cardBox.right + 1 &&
            box.top >= cardBox.top - 1 &&
            box.bottom <= cardBox.bottom + 1;
          return inside
            ? []
            : [
                `${cardName}: ${element.className || element.tagName} ` +
                  `(${box.left.toFixed(1)},${box.top.toFixed(1)}–` +
                  `${box.right.toFixed(1)},${box.bottom.toFixed(1)}) exceeds ` +
                  `card (${cardBox.left.toFixed(1)},${cardBox.top.toFixed(1)}–` +
                  `${cardBox.right.toFixed(1)},${cardBox.bottom.toFixed(1)})`,
              ];
        });
      }),
  );
  expect(violations).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}

test("visual preview, routing, themes and persistence", async ({ page }) => {
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
  await expect(page.locator(".connection-node-card")).toHaveCount(8);
  await expect(page.locator(".gateway-node-card")).toHaveCount(1);
  await expect(page.locator(".react-flow__edge")).toHaveCount(8);
  const rockwell = page
    .getByTestId("connection-node-rockwell_allen_bradley")
    .first();
  const gateway = page.getByTestId("gateway-node");
  await expect(rockwell.locator(".node-header")).toHaveText(
    "Assembly ControlLogix",
  );
  await expect(rockwell.locator(".node-header .node-type")).toHaveCount(0);
  await expect(gateway.locator(".gateway-header")).toHaveText("SDEX Suite");
  await expect(gateway.getByText("SDEX Gateway", { exact: true })).toHaveCount(
    0,
  );
  await expect(gateway.locator(".gateway-interface-label--top")).toContainText(
    "eth1",
  );
  await expect(
    gateway.locator(".gateway-interface-label--bottom"),
  ).toContainText("eth2");
  const flowKeyframes = await page
    .locator(".edge-data-flow")
    .first()
    .evaluate((element) => {
      const animation = element.getAnimations()[0];
      if (!(animation?.effect instanceof KeyframeEffect)) return [];
      return animation.effect
        .getKeyframes()
        .map((keyframe) => String(keyframe.strokeDashoffset ?? ""));
    });
  expect(flowKeyframes.at(-1)).toContain("-0.073");
  await expect(
    page.locator(".gateway-node-card .react-flow__handle-top"),
  ).toHaveCount(1);
  await expect(
    page.locator(".gateway-node-card .react-flow__handle-bottom"),
  ).toHaveCount(1);
  await assertNodesDoNotOverlap(page);
  await assertVisualContentStaysInsideCards(page);
  await assertImagesStayInsideShells(page);

  const standardGeometry = await rockwell.evaluate((card) => {
    const icon = card.querySelector(".node-icon-shell")?.getBoundingClientRect();
    const badge = card.querySelector(".status-badge")?.getBoundingClientRect();
    return icon && badge ? { iconRight: icon.right, badgeLeft: badge.left } : null;
  });
  expect(standardGeometry).not.toBeNull();
  expect(standardGeometry?.badgeLeft).toBeGreaterThan(
    standardGeometry?.iconRight ?? Number.POSITIVE_INFINITY,
  );

  const gatewayGeometry = await gateway.evaluate((card) => {
    const cardBox = card.getBoundingClientRect();
    const topLabel = card
      .querySelector(".gateway-interface-label--top")
      ?.getBoundingClientRect();
    const bottomLabel = card
      .querySelector(".gateway-interface-label--bottom")
      ?.getBoundingClientRect();
    const topHandle = card
      .querySelector(".react-flow__handle-top")
      ?.getBoundingClientRect();
    const bottomHandle = card
      .querySelector(".react-flow__handle-bottom")
      ?.getBoundingClientRect();
    const badge = card.querySelector(".status-badge")?.getBoundingClientRect();
    const locked = card.querySelector(".locked-label")?.getBoundingClientRect();
    if (
      !topLabel ||
      !bottomLabel ||
      !topHandle ||
      !bottomHandle ||
      !badge ||
      !locked
    ) {
      return null;
    }
    const centerX = (box: DOMRect) => box.left + box.width / 2;
    return {
      cardLeft: cardBox.left,
      cardRight: cardBox.right,
      cardTop: cardBox.top,
      cardBottom: cardBox.bottom,
      topCenterY: topLabel.top + topLabel.height / 2,
      bottomCenterY: bottomLabel.top + bottomLabel.height / 2,
      topXDelta: Math.abs(centerX(topLabel) - centerX(topHandle)),
      bottomXDelta: Math.abs(centerX(bottomLabel) - centerX(bottomHandle)),
      badgeLeft: badge.left,
      lockedLeft: locked.left,
      lockedRight: locked.right,
      badgeRight: badge.right,
    };
  });
  expect(gatewayGeometry).not.toBeNull();
  expect(gatewayGeometry?.topCenterY).toBeLessThan(
    gatewayGeometry?.cardTop ?? Number.NEGATIVE_INFINITY,
  );
  expect(gatewayGeometry?.bottomCenterY).toBeGreaterThan(
    gatewayGeometry?.cardBottom ?? Number.POSITIVE_INFINITY,
  );
  expect(gatewayGeometry?.topXDelta).toBeLessThan(2);
  expect(gatewayGeometry?.bottomXDelta).toBeLessThan(2);
  expect(gatewayGeometry?.badgeLeft).toBeGreaterThanOrEqual(
    gatewayGeometry?.cardLeft ?? Number.POSITIVE_INFINITY,
  );
  expect(gatewayGeometry?.lockedLeft).toBeGreaterThanOrEqual(
    gatewayGeometry?.badgeRight ?? Number.POSITIVE_INFINITY,
  );
  expect(gatewayGeometry?.lockedRight).toBeLessThanOrEqual(
    gatewayGeometry?.cardRight ?? Number.NEGATIVE_INFINITY,
  );

  const topologyResponse = await page.request.get("/api/topology");
  expect(topologyResponse.ok()).toBe(true);
  const topology = (await topologyResponse.json()) as {
    gateway: { id: string };
    nodes: Array<{ id: string }>;
    edges: Array<{
      source: string;
      target: string;
      target_handle: string | null;
    }>;
  };
  expect(topology.edges).toHaveLength(8);
  expect(
    topology.edges.filter((edge) => edge.target_handle === "sdex-eth1"),
  ).toHaveLength(4);
  expect(
    topology.edges.filter((edge) => edge.target_handle === "sdex-eth2"),
  ).toHaveLength(4);
  for (const edge of topology.edges) {
    expect(topology.nodes.some((node) => node.id === edge.source)).toBe(true);
    expect(edge.target).toBe(topology.gateway.id);
  }

  await chooseOption(page, "Theme", "Light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.waitForTimeout(100);
  const lightCanvas = await page.evaluate(() => {
    const tokens = getComputedStyle(document.documentElement);
    const canvas = document.querySelector<HTMLElement>(
      ".topology-canvas .react-flow",
    );
    const dot = document.querySelector<SVGCircleElement>(
      ".canvas-background circle",
    );
    return {
      backgroundToken: tokens.getPropertyValue("--canvas-bg").trim(),
      dotToken: tokens.getPropertyValue("--canvas-dot").trim(),
      canvasBackground: canvas ? getComputedStyle(canvas).backgroundColor : "",
      dotFill: dot ? getComputedStyle(dot).fill : "",
      dotOpacity: dot ? getComputedStyle(dot).opacity : "",
    };
  });
  expect(lightCanvas).toEqual({
    backgroundToken: "#dfdfdf",
    dotToken: "#b6bac6",
    canvasBackground: "rgb(223, 223, 223)",
    dotFill: "rgb(182, 186, 198)",
    dotOpacity: "1",
  });
  await expect(page.locator(".top-bar .brand-logo")).toHaveCount(1);
  await expect(page.locator(".top-bar .brand-mark")).toHaveCount(0);
  await page.screenshot({
    path: `${screenshotDirectory}/01-overview-light-1440x1000.png`,
  });
  await page.screenshot({
    path: `${screenshotDirectory}/02-branding-light.png`,
    clip: { x: 0, y: 0, width: 560, height: 92 },
  });

  await chooseOption(page, "Theme", "Dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.waitForTimeout(100);
  await page.screenshot({
    path: `${screenshotDirectory}/03-overview-dark-1440x1000.png`,
  });

  await screenshotAtIntrinsicSize(
    rockwell,
    `${screenshotDirectory}/04-device-card-rockwell.png`,
  );
  await rockwell.dblclick();
  await expect(page.getByTestId("details-drawer")).toBeVisible();
  await page.getByTestId("details-drawer").screenshot({
    path: `${screenshotDirectory}/05-rockwell-details.png`,
  });
  await page.getByRole("button", { name: "Close details" }).click();

  await screenshotAtIntrinsicSize(
    gateway,
    `${screenshotDirectory}/06-sdex-node.png`,
    54,
  );
  await gateway.dblclick();
  await expect(
    page.getByRole("heading", { name: "Network interfaces" }),
  ).toBeVisible();
  await page.getByTestId("details-drawer").screenshot({
    path: `${screenshotDirectory}/07-sdex-details.png`,
  });
  await page.getByRole("button", { name: "Close details" }).click();

  await chooseOption(page, "Theme", "Light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const firstCable = page
    .getByRole("button", { name: /^Configure cable from / })
    .first();
  const firstFlow = firstCable.locator(".edge-data-flow");
  await expect(firstFlow).toHaveAttribute("data-flow-direction", "forward");
  await expect(firstFlow).toHaveCSS("animation-direction", "normal");
  await expect(page.locator(".edge-data-flow").nth(1)).toHaveAttribute(
    "data-flow-direction",
    "forward",
  );
  await firstCable.dispatchEvent("dblclick");
  const cableDialog = page.getByRole("dialog", { name: "Cable appearance" });
  await expect(cableDialog).toBeVisible();
  await page.getByRole("tab", { name: "Data flow" }).click();
  const reverseFlowSwitch = page.getByRole("switch", {
    name: "Reverse Flow",
  });
  const reverseFlowLabel = cableDialog.getByText("Reverse Flow", {
    exact: true,
  });
  await expect(reverseFlowSwitch).not.toBeChecked();
  await cableDialog.screenshot({
    path: `${screenshotDirectory}/08-data-flow-default.png`,
  });

  await page.getByRole("textbox", { name: "Hex color" }).fill("#FF4DF3");
  await reverseFlowLabel.click();
  await expect(reverseFlowSwitch).toBeChecked();
  await cableDialog.screenshot({
    path: `${screenshotDirectory}/09-data-flow-reverse.png`,
  });
  await page.getByRole("tab", { name: "Cable" }).click();
  await page.getByRole("textbox", { name: "Hex color" }).fill("#123456");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("Cable style saved.")).toBeAttached();
  await cableDialog.getByRole("button", { name: "Close" }).click();
  await expect(firstFlow).toHaveAttribute("data-flow-direction", "reverse");
  await expect(firstFlow).toHaveCSS("animation-direction", "reverse");
  await expect(page.locator(".edge-data-flow").nth(1)).toHaveAttribute(
    "data-flow-direction",
    "forward",
  );

  await page.reload();
  await expect(page.locator(".react-flow__edge")).toHaveCount(8);
  await expect(firstFlow).toHaveAttribute("data-flow-direction", "reverse");
  await firstCable.dispatchEvent("dblclick");
  await expect(page.getByRole("textbox", { name: "Hex color" })).toHaveValue(
    "#123456",
  );
  await page.getByRole("tab", { name: "Data flow" }).click();
  await expect(page.getByRole("textbox", { name: "Hex color" })).toHaveValue(
    "#FF4DF3",
  );
  await expect(reverseFlowSwitch).toBeChecked();
  await reverseFlowLabel.click();
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("Cable style saved.")).toBeAttached();
  await cableDialog.getByRole("button", { name: "Close" }).click();
  await expect(firstFlow).toHaveAttribute("data-flow-direction", "forward");
  await expect(firstFlow).toHaveCSS("animation-direction", "normal");

  await chooseOption(page, "Theme", "Dark");
  await page.getByRole("combobox", { name: "Refresh interval" }).click();
  await page.screenshot({
    path: `${screenshotDirectory}/10-dropdown-dark.png`,
    clip: { x: 0, y: 0, width: 1440, height: 330 },
  });
  await page.keyboard.press("Escape");

  await chooseOption(page, "Theme", "Light");
  await page.getByRole("combobox", { name: "Refresh interval" }).click();
  await page.screenshot({
    path: `${screenshotDirectory}/11-dropdown-light.png`,
    clip: { x: 0, y: 0, width: 1440, height: 330 },
  });
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.getByRole("button", { name: "Fit topology" }).click();
  await page.waitForTimeout(500);
  await page.screenshot({
    path: `${screenshotDirectory}/12-overview-light-1920x1080.png`,
  });
  await assertNodesDoNotOverlap(page);

  expect(failedResponses).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("compact viewports keep settings and the data source accessible", async ({ page }) => {
  for (const width of [1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByTestId("gateway-node")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

    const mockBadge = page.getByLabel("Data source: Mock Mode", { exact: true });
    if (await mockBadge.isVisible()) {
      await expect(mockBadge).toHaveText("Mock Mode");
    } else {
      const statusTrigger = page.getByRole("button", { name: "SDEX status details" });
      await expect(statusTrigger).toBeVisible();
      await statusTrigger.click();
      const status = page.getByRole("dialog", { name: "SDEX status details" });
      await expect(status).toContainText("Mock Mode");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.keyboard.press("Escape");
      await expect(status).not.toBeVisible();
    }

    await page.getByRole("button", { name: "Settings", exact: true }).click();
    const settings = page.getByRole("dialog", { name: "SDEX settings" });
    await expect(settings).toBeVisible();
    await expect(settings.getByLabel("SDEX Base URL")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(settings).not.toBeVisible();
  }
});
