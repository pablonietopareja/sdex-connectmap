import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

import { canonicalIconAssetsPlugin } from "./icon-assets-plugin";

const iconsDirectory = fileURLToPath(new URL("../icons/", import.meta.url));

export default defineConfig({
  publicDir: false,
  plugins: [canonicalIconAssetsPlugin(iconsDirectory), react()],
  server: {
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8080",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    restoreMocks: true,
  },
});
