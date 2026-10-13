import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Plugin } from "vite";

export const ICON_FILENAMES = [
  "Eth_Connector.svg",
  "Fanuc.svg",
  "Modbus.svg",
  "MQTT.svg",
  "OPC_UA_Server.svg",
  "Rockwell.svg",
  "S7.svg",
  "S7_2.svg",
  "SDEX.svg",
  "SDEX_ConnectMap_logo.svg",
  "Sinumerik.svg",
  "Switch.svg",
] as const;

const ICON_ROUTE_PREFIX = "/icons/";

function readCanonicalIcon(iconsDirectory: string, filename: string): Buffer {
  try {
    return readFileSync(resolve(iconsDirectory, filename));
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`Cannot read canonical icon ${filename}: ${reason}`);
  }
}

export function canonicalIconAssetsPlugin(iconsDirectory: string): Plugin {
  const allowedFilenames = new Set<string>(ICON_FILENAMES);
  let command: "build" | "serve" = "serve";

  return {
    name: "sdex-canonical-icon-assets",
    configResolved(config) {
      command = config.command;
    },
    buildStart() {
      if (command !== "build") return;
      for (const filename of ICON_FILENAMES) {
        this.emitFile({
          type: "asset",
          fileName: `icons/${filename}`,
          source: readCanonicalIcon(iconsDirectory, filename),
        });
      }
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const requestUrl = new URL(request.url ?? "/", "http://vite.local");
        if (!requestUrl.pathname.startsWith(ICON_ROUTE_PREFIX)) {
          next();
          return;
        }

        let filename: string;
        try {
          filename = decodeURIComponent(
            requestUrl.pathname.slice(ICON_ROUTE_PREFIX.length),
          );
        } catch {
          response.statusCode = 400;
          response.end("Invalid icon path.");
          return;
        }

        if (!allowedFilenames.has(filename)) {
          response.statusCode = 404;
          response.end("Icon not found.");
          return;
        }
        if (request.method !== "GET" && request.method !== "HEAD") {
          response.statusCode = 405;
          response.setHeader("Allow", "GET, HEAD");
          response.end();
          return;
        }

        let source: Buffer;
        try {
          source = readCanonicalIcon(iconsDirectory, filename);
        } catch (error) {
          server.config.logger.error(
            error instanceof Error ? error.message : String(error),
          );
          response.statusCode = 404;
          response.end("Icon not found.");
          return;
        }

        response.statusCode = 200;
        response.setHeader("Content-Type", "image/svg+xml; charset=utf-8");
        response.setHeader("Content-Length", String(source.byteLength));
        response.setHeader("Cache-Control", "no-cache");
        response.setHeader("X-Content-Type-Options", "nosniff");
        if (request.method === "HEAD") {
          response.end();
          return;
        }
        response.end(source);
      });
    },
  };
}
