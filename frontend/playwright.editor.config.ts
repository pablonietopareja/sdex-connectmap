import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("./", import.meta.url));
const python = process.env.CONNECTMAP_TEST_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/editor.e2e.ts",
  outputDir: "./test-results/editor",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 12_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8766",
    browserName: "chromium",
    headless: true,
    viewport: { width: 1920, height: 1080 },
    colorScheme: "dark",
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      `npm run build && "${python}" ../scripts/e2e_server.py --port 8766 --scenario editor_preview`,
    cwd: frontendRoot,
    url: "http://127.0.0.1:8766/api/health",
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
