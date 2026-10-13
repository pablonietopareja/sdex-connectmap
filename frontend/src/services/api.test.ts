import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("ConnectMap API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("surfaces the backend validation detail without reflecting arbitrary bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "validation_error",
              message: "Request validation failed.",
              details: [
                {
                  location: ["body", "refresh_interval_seconds"],
                  message: "refresh interval is not supported",
                  type: "value_error",
                },
              ],
            },
          }),
          {
            status: 422,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );

    await expect(
      api.updateSettings({ refresh_interval_seconds: 2 }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "refresh interval is not supported",
    });
  });

  it("persists and resets one edge style through its encoded stable id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            edge_id: "sdex-to-modbus:line-1",
            sheath_color: "#123456",
            flow_color: "#ABCDEF",
            reverse_flow: true,
            updated_at: "2026-07-29T10:00:00Z",
            schema_version: 1,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await api.updateEdgeStyle("sdex-to-modbus:line-1", {
      sheath_color: "#123456",
      flow_color: "#ABCDEF",
      reverse_flow: true,
    });
    await api.resetEdgeStyle("sdex-to-modbus:line-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/edges/sdex-to-modbus%3Aline-1/style",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          sheath_color: "#123456",
          flow_color: "#ABCDEF",
          reverse_flow: true,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/edges/sdex-to-modbus%3Aline-1/style",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("uses only the local visual-topology API for Racks, links, and routes", async () => {
    const json = { "Content-Type": "application/json" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "rack:one",
            type: "rack",
            name: "Line 1",
            description: null,
            position: { x: 40, y: 80 },
            width: 1000,
            height: 300,
            external_interface: null,
            rows: 1,
            columns: 3,
            capacity: 3,
            collapsed: false,
            aggregate: {
              status: "unknown",
              total: 0,
              connected: 0,
              disconnected: 0,
              disabled: 0,
              unknown: 0,
              degraded: 0,
              missing: 0,
              animated: false,
            },
            schema_version: 1,
            created_at: "2026-07-31T10:00:00Z",
            updated_at: "2026-07-31T10:00:00Z",
          }),
          { status: 200, headers: json },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            rack_id: "rack:one",
            connection_id: "modbus:line-1",
            row: 0,
            column: 0,
            missing: false,
            connection: null,
          }),
          { status: 200, headers: json },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            edge_id: "visual-link:one",
            routing_mode: "orthogonal",
            waypoints: [
              { id: "corner:one", x: 120, y: 220, kind: "corner", order: 0 },
            ],
            schema_version: 1,
            updated_at: "2026-07-31T10:00:00Z",
          }),
          { status: 200, headers: json },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: json,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await api.createVisualElement({
      type: "rack",
      name: "Line 1",
      rows: 1,
      columns: 3,
      position: { x: 40, y: 80 },
    });
    await api.addRackMember("rack:one", {
      connection_id: "modbus:line-1",
      row: 0,
      column: 0,
    });
    await api.updateEdgeRoute("visual-link:one", {
      routing_mode: "orthogonal",
      waypoints: [
        { id: "corner:one", x: 120, y: 220, kind: "corner", order: 0 },
      ],
    });
    await api.resetEdgeRoute("visual-link:one");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/visual-elements",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/racks/rack%3Aone/members",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/edges/visual-link%3Aone/route",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/edges/visual-link%3Aone/route",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("192.168")),
    ).toBe(false);
  });
});
