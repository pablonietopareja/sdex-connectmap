import { describe, expect, it } from "vitest";
import { makeNode, makeSnapshot } from "../test/fixtures";
import type { TopologyAlarm } from "../types";
import { deduplicateAlarms, deriveTopologyAlarms } from "./alarms";

describe("alarm model", () => {
  it("deduplicates semantic IDs, preserves richer context, and raises severity", () => {
    const alarms: TopologyAlarm[] = [
      {
        id: "module_refresh_failed:opcua",
        severity: "info",
        title: "Refresh failed",
        description: "Failed",
      },
      {
        id: "module_refresh_failed:opcua",
        severity: "error",
        title: "OPC UA module refresh failed",
        description: "The endpoint returned an authentication error.",
        source: "opcua",
      },
    ];

    expect(deduplicateAlarms(alarms)).toEqual([
      {
        id: "module_refresh_failed:opcua",
        severity: "error",
        title: "OPC UA module refresh failed",
        description: "The endpoint returned an authentication error.",
        source: "opcua",
      },
    ]);
  });

  it("derives stable IDs, severities, sources, and the real-session TLS warning", () => {
    const snapshot = makeSnapshot(
      [
        makeNode({
          id: "s7:unresolved",
          interface_assignment: {
            resolved: false,
            interface_name: null,
            source: "unresolved",
            reason: "No external prefix matched.",
          },
        }),
      ],
      {
        partial: true,
        last_error: "Some SDEX modules could not be refreshed.",
        module_results: [
          { module: "fanuc", status: "unavailable", count: 0 },
          { module: "opcua client", status: "forbidden", count: 0 },
          {
            module: "sinumerik",
            status: "temporary_error",
            count: 0,
            error: "HTTP 503",
          },
        ],
      },
    );

    const alarms = deriveTopologyAlarms(snapshot, {
      tlsVerificationDisabled: true,
    });

    expect(alarms.map((alarm) => alarm.id)).toEqual([
      "module_forbidden:opcua-client",
      "module_refresh_failed",
      "module_refresh_failed:sinumerik",
      "module_unavailable:fanuc",
      "partial_discovery",
      "tls_verification_disabled",
      "unresolved_interface_assignments",
    ]);
    expect(alarms).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "module_forbidden:opcua-client",
          severity: "warning",
          source: "opcua client",
        }),
        expect.objectContaining({
          id: "tls_verification_disabled",
          severity: "warning",
        }),
      ]),
    );
  });

  it("does not create a TLS alarm in Mock Mode", () => {
    const alarms = deriveTopologyAlarms(
      makeSnapshot(undefined, { mock_mode: true }),
      { tlsVerificationDisabled: true },
    );

    expect(alarms).toEqual([]);
  });

  it("collapses stale state and its detailed error into one active error", () => {
    const alarms = deriveTopologyAlarms(
      makeSnapshot(undefined, {
        stale: true,
        partial: true,
        last_error: "The SDEX request timed out after 15 seconds.",
        module_results: [
          { module: "modbus", status: "temporary_error", count: 0 },
        ],
      }),
    );

    expect(alarms).toHaveLength(1);
    expect(alarms[0]).toMatchObject({
      id: "sdex_unreachable",
      severity: "error",
      description: "The SDEX request timed out after 15 seconds.",
    });
  });

  it("is deterministic when module discovery results arrive in another order", () => {
    const modules = [
      { module: "zeta", status: "unavailable" as const, count: 0 },
      { module: "alpha", status: "parse_error" as const, count: 0 },
    ];
    const forward = deriveTopologyAlarms(
      makeSnapshot(undefined, { partial: true, module_results: modules }),
    );
    const reverse = deriveTopologyAlarms(
      makeSnapshot(undefined, {
        partial: true,
        module_results: [...modules].reverse(),
      }),
    );

    expect(reverse).toEqual(forward);
  });
});
