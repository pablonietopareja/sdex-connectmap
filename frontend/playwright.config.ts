import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("./", import.meta.url));
const python = process.env.CONNECTMAP_TEST_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/visual.e2e.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8765",
    browserName: "chromium",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    colorScheme: "light",
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      `npm run build && "${python}" ../scripts/e2e_server.py --port 8765 --scenario visual_preview`,
    cwd: frontendRoot,
    url: "http://127.0.0.1:8765/api/health",
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
