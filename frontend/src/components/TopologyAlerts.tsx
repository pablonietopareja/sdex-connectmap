import type { TopologySnapshot } from "../types";
import { AlertIcon, InfoIcon } from "./icons";

export function TopologyAlerts({ snapshot }: { snapshot: TopologySnapshot }) {
  const unresolved = snapshot.nodes.filter(
    (node) =>
      node.enabled &&
      node.interface_assignment !== undefined &&
      !node.interface_assignment?.resolved,
  );
  if (
    !snapshot.stale &&
    !snapshot.partial &&
    !snapshot.last_error &&
    unresolved.length === 0
  ) {
    return null;
  }
  const failedModules = snapshot.module_results
    .filter((result) => result.status !== "ok" && result.status !== "unavailable")
    .map((result) => result.module);

  return (
    <div className="topology-alerts" role="status">
      {snapshot.stale && (
        <div className="topology-alert stale-alert">
          <AlertIcon />
          <span>
            <strong>Communication with SDEX is unavailable.</strong> The last valid
            snapshot remains visible and device states have not been changed.
          </span>
        </div>
      )}
      {!snapshot.stale && snapshot.partial && (
        <div className="topology-alert partial-alert">
          <InfoIcon />
          <span>
            <strong>Discovery is partial.</strong>{" "}
            {failedModules.length > 0
              ? `Could not read: ${failedModules.join(", ")}.`
              : "One or more SDEX modules are unavailable or restricted."}
          </span>
        </div>
      )}
      {!snapshot.stale && snapshot.last_error && (
        <div className="topology-alert partial-alert">
          <InfoIcon />
          <span>{snapshot.last_error}</span>
        </div>
      )}
      {!snapshot.stale && unresolved.length > 0 && (
        <div className="topology-alert interface-alert">
          <InfoIcon />
          <span>
            <strong>
              {unresolved.length} connection
              {unresolved.length === 1 ? "" : "s"} need an SDEX interface.
            </strong>{" "}
            No eth1/eth2 cable is drawn until a real prefix or an explicit
            fallback resolves the route.
          </span>
        </div>
      )}
    </div>
  );
}
