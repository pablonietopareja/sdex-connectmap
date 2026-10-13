import type {
  AlarmDerivationOptions,
  AlarmSeverity,
  TopologyAlarm,
  TopologySnapshot,
} from "../types";

const severityRank: Record<AlarmSeverity, number> = {
  error: 0,
  warning: 1,
  info: 2,
};

function alarmIdSegment(value: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "unknown";
}

function preferText(current: string, candidate: string): string {
  return candidate.trim().length > current.trim().length ? candidate : current;
}

/**
 * De-duplicate active conditions by semantic ID and return a deterministic
 * severity/ID order. Higher severity wins if two producers report one ID.
 */
export function deduplicateAlarms(
  alarms: readonly TopologyAlarm[],
): TopologyAlarm[] {
  const byId = new Map<string, TopologyAlarm>();

  for (const alarm of alarms) {
    const existing = byId.get(alarm.id);
    if (!existing) {
      byId.set(alarm.id, { ...alarm });
      continue;
    }

    const incomingIsMoreSpecific = Boolean(alarm.source && !existing.source);
    const existingIsMoreSpecific = Boolean(existing.source && !alarm.source);

    byId.set(alarm.id, {
      ...existing,
      severity:
        severityRank[alarm.severity] < severityRank[existing.severity]
          ? alarm.severity
          : existing.severity,
      title: incomingIsMoreSpecific
        ? alarm.title
        : existingIsMoreSpecific
          ? existing.title
          : preferText(existing.title, alarm.title),
      description: incomingIsMoreSpecific
        ? alarm.description
        : existingIsMoreSpecific
          ? existing.description
          : preferText(existing.description, alarm.description),
      timestamp: existing.timestamp ?? alarm.timestamp,
      source: existing.source ?? alarm.source,
    });
  }

  return [...byId.values()].sort(
    (left, right) =>
      severityRank[left.severity] - severityRank[right.severity] ||
      left.id.localeCompare(right.id),
  );
}

function moduleAlarm(
  module: TopologySnapshot["module_results"][number],
): TopologyAlarm | null {
  const source = module.module;
  const moduleId = alarmIdSegment(source);
  const suffix = module.error?.trim();

  switch (module.status) {
    case "ok":
      return null;
    case "unavailable":
      return {
        id: `module_unavailable:${moduleId}`,
        severity: "warning",
        title: `${source} is unavailable`,
        description:
          suffix || "This SDEX module is not available in the current installation.",
        source,
      };
    case "forbidden":
      return {
        id: `module_forbidden:${moduleId}`,
        severity: "warning",
        title: `${source} is restricted`,
        description:
          suffix || "The current SDEX account cannot read this module.",
        source,
      };
    case "authentication_error":
      return {
        id: `module_authentication_error:${moduleId}`,
        severity: "error",
        title: `${source} authentication failed`,
        description:
          suffix || "SDEX rejected the authenticated request for this module.",
        source,
      };
    case "default_password":
      return {
        id: `module_default_password:${moduleId}`,
        severity: "error",
        title: `${source} requires a password change`,
        description:
          suffix || "SDEX reports that this account still uses its default password.",
        source,
      };
    case "temporary_error":
      return {
        id: `module_refresh_failed:${moduleId}`,
        severity: "warning",
        title: `${source} could not be refreshed`,
        description:
          suffix || "A temporary SDEX error prevented this module from refreshing.",
        source,
      };
    case "parse_error":
      return {
        id: `module_parse_error:${moduleId}`,
        severity: "warning",
        title: `${source} response was not recognized`,
        description:
          suffix || "SDEX responded, but ConnectMap could not interpret the module data.",
        source,
      };
  }
}

/** Build the current alarm set from source topology without storing an event log. */
export function deriveTopologyAlarms(
  snapshot: TopologySnapshot,
  options: AlarmDerivationOptions = {},
): TopologyAlarm[] {
  const alarms: TopologyAlarm[] = (snapshot.alarms ?? []).map((alarm) => ({
    ...alarm,
    timestamp: alarm.timestamp ?? alarm.occurred_at ?? null,
  }));

  if (snapshot.stale) {
    alarms.push({
      id: "sdex_unreachable",
      severity: "error",
      title: "Communication with SDEX is unavailable",
      description:
        "The last valid snapshot remains visible and device states have not been changed.",
    });
  } else {
    if (snapshot.partial) {
      alarms.push({
        id: "partial_discovery",
        severity: "warning",
        title: "Discovery is partial",
        description:
          "One or more SDEX modules are unavailable, restricted, or could not be read.",
      });
    }

    for (const result of snapshot.module_results) {
      const alarm = moduleAlarm(result);
      if (alarm) alarms.push(alarm);
    }

    const unresolvedCount = snapshot.nodes.filter(
      (node) =>
        node.enabled &&
        !(node.local_service && node.interface_scope === "gateway-local") &&
        node.interface_assignment !== undefined &&
        !node.interface_assignment?.resolved,
    ).length;
    if (unresolvedCount > 0) {
      alarms.push({
        id: "unresolved_interface_assignments",
        severity: "warning",
        title: `${unresolvedCount} connection${unresolvedCount === 1 ? "" : "s"} need an SDEX interface`,
        description:
          "No eth1/eth2 cable is drawn until a real prefix or explicit fallback resolves each route.",
        source: "networking",
      });
    }
  }

  if (snapshot.last_error) {
    alarms.push({
      id: snapshot.stale ? "sdex_unreachable" : "module_refresh_failed",
      severity: snapshot.stale ? "error" : "warning",
      title: snapshot.stale
        ? "Communication with SDEX is unavailable"
        : "Some SDEX modules could not be refreshed",
      description: snapshot.last_error,
      source: "discovery",
    });
  }

  if (options.tlsVerificationDisabled && !snapshot.mock_mode) {
    alarms.push({
      id: "tls_verification_disabled",
      severity: "warning",
      title: "TLS certificate verification is disabled",
      description:
        "This real SDEX session encrypts traffic but does not verify the server certificate identity.",
      source: "transport security",
    });
  }

  return deduplicateAlarms(alarms);
}
