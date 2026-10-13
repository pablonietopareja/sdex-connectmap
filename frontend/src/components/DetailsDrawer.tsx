import { useEffect } from "react";
import { CONNECTION_PRESENTATION } from "../constants";
import type {
  ConnectionNode,
  JsonValue,
  NetworkInterface,
  Subchannel,
} from "../types";
import { displayAddress, formatTimestamp, nodeIcon } from "../utils";
import { CloseIcon } from "./icons";
import { SelectMenu } from "./SelectMenu";
import { StatusBadge } from "./StatusBadge";

const SENSITIVE_KEY = /password|secret|token|nonce|signature|authorization|private|certificate/i;

function renderMetadataValue(value: JsonValue): string {
  if (value === null) return "—";
  if (Array.isArray(value)) return value.map(renderMetadataValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function isDisplaySafeMetadata(value: JsonValue): boolean {
  if (value === null || typeof value !== "object") return true;
  return Array.isArray(value)
    ? value.every((entry) => entry === null || typeof entry !== "object")
    : false;
}

function DetailRow({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`detail-row${wide ? " wide" : ""}`}>
      <dt>{label}</dt>
      <dd>{value || "—"}</dd>
    </div>
  );
}

function capabilitySubchannels(node: ConnectionNode): Subchannel[] {
  const raw = node.capabilities?.subchannels;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return node.subchannels ?? [];
  }
  return Object.entries(raw).flatMap(([name, value]) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const statusValue = value.status;
    const status =
      statusValue === "connected" ||
      statusValue === "disconnected" ||
      statusValue === "disabled" ||
      statusValue === "unlicensed" ||
      statusValue === "degraded" ||
      statusValue === "unknown"
        ? statusValue
        : "unknown";
    return [
      {
        name: name.toUpperCase(),
        enabled:
          typeof value.enabled === "boolean" ? value.enabled : undefined,
        status,
        reason: typeof value.reason === "string" ? value.reason : undefined,
      },
    ];
  });
}

export function DetailsDrawer({
  node,
  networkInterfaces = [],
  onInterfaceOverride,
  interfaceOverrideBusy = false,
  onClose,
}: {
  node: ConnectionNode | null;
  networkInterfaces?: NetworkInterface[];
  onInterfaceOverride?: (
    connectionId: string,
    interfaceName: "eth1" | "eth2" | null,
  ) => Promise<void>;
  interfaceOverrideBusy?: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!node) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [node, onClose]);

  if (!node) return null;
  const presentation = CONNECTION_PRESENTATION[node.type];
  const safeMetadata = Object.entries(node.metadata).filter(
    ([key, value]) =>
      !SENSITIVE_KEY.test(key) &&
      isDisplaySafeMetadata(value) &&
      value !== null &&
      value !== "" &&
      value !== undefined,
  );
  const subchannels = capabilitySubchannels(node);
  const assignment = node.interface_assignment;
  const isGateway = node.type === "sdex_gateway";

  return (
    <aside
      className="details-drawer"
      role="dialog"
      aria-modal="false"
      aria-labelledby="details-title"
      data-testid="details-drawer"
    >
      <header className="details-header">
        <div
          className={`details-icon${isGateway ? " details-icon-gateway" : ""}`}
        >
          <img src={nodeIcon(node)} alt="" />
        </div>
        <div>
          <span>{presentation.label}</span>
          <h2 id="details-title">{node.display_name}</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          aria-label="Close details"
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </header>

      <div className="details-status">
        <StatusBadge status={node.enabled ? node.status : "disabled"} />
        {node.stale && <span className="stale-chip">Stale snapshot</span>}
      </div>
      {node.status_reason && (
        <p className="details-reason">{node.status_reason}</p>
      )}
      {node.local_service && (
        <p className="details-local-service" role="note">
          <strong>Gateway-local endpoint.</strong> Connected means the endpoint is enabled while the SDEX gateway API is reachable. Active OPC UA client-session telemetry is unavailable and is not inferred.
        </p>
      )}

      <section className="details-section">
        <h3>Connection</h3>
        <dl className="details-grid">
          <DetailRow label="Type" value={presentation.label} />
          <DetailRow label="Subtype" value={node.subtype} />
          <DetailRow label="Address" value={displayAddress(node)} />
          <DetailRow label="Port" value={node.port} />
          {node.endpoint_url && (
            <DetailRow label="Endpoint URL" value={node.endpoint_url} wide />
          )}
          <DetailRow label="Enabled" value={node.enabled ? "Yes" : "No"} />
          <DetailRow
            label="Licensed"
            value={
              node.licensed === null || node.licensed === undefined
                ? "Not reported"
                : node.licensed
                  ? "Yes"
                  : "No"
            }
          />
          <DetailRow label="Source module" value={node.source_module} wide />
          {!isGateway && (
            <>
              <DetailRow
                label="SDEX interface"
                value={
                  assignment?.resolved
                    ? assignment.interface_name
                    : node.interface_scope === "gateway-local"
                    ? "All external SDEX interfaces"
                    : "Unresolved"
                }
              />
              <DetailRow
                label="Assignment source"
                value={assignment?.source?.replaceAll("_", " ") ?? "Not reported"}
              />
              {assignment?.reason && (
                <DetailRow
                  label="Assignment reason"
                  value={assignment.reason}
                  wide
                />
              )}
              {node.local_service && (
                <>
                  <DetailRow
                    label="Interface scope"
                    value={node.interface_scope?.replaceAll("-", " ") ?? "Not reported"}
                  />
                  <DetailRow
                    label="Session telemetry"
                    value={node.session_telemetry ?? "Not reported"}
                  />
                  <DetailRow
                    label="External candidates"
                    value={assignment?.candidate_interfaces?.join(", ") || "eth1, eth2"}
                    wide
                  />
                </>
              )}
            </>
          )}
        </dl>
        {!isGateway && onInterfaceOverride && (
          <div className="interface-override">
            <div>
              <strong>Manual interface override</strong>
              <span>
                Fallback only. Automatic matching is preferred when SDEX reports
                sufficient network data.
              </span>
            </div>
            <fieldset disabled={interfaceOverrideBusy}>
              <legend className="sr-only">Manual interface override</legend>
              <SelectMenu
                ariaLabel="Manual SDEX interface override"
                value={
                  assignment?.source === "manual_override" &&
                  (assignment.interface_name === "eth1" ||
                    assignment.interface_name === "eth2")
                    ? assignment.interface_name
                    : "auto"
                }
                options={[
                  { value: "auto", label: "Automatic" },
                  { value: "eth1", label: "eth1" },
                  { value: "eth2", label: "eth2" },
                ] as const}
                onChange={(value) =>
                  void onInterfaceOverride(
                    node.id,
                    value === "auto" ? null : value,
                  )
                }
              />
            </fieldset>
          </div>
        )}
      </section>

      {isGateway && (
        <section className="details-section">
          <h3>Network interfaces</h3>
          {networkInterfaces.length > 0 ? (
            <div className="network-interface-list">
              {networkInterfaces.map((networkInterface) => (
                <article key={networkInterface.name}>
                  <header>
                    <strong>{networkInterface.name}</strong>
                    <span>{networkInterface.source.replaceAll("_", " ")}</span>
                  </header>
                  {networkInterface.addresses.length > 0 ? (
                    <dl>
                      {networkInterface.addresses.map((address) => (
                        <div
                          key={`${address.address}/${address.prefix_length ?? "unknown"}`}
                        >
                          <dt>IP / prefix</dt>
                          <dd>
                            {address.address}
                            {address.prefix_length === null
                              ? " / prefix unavailable"
                              : `/${address.prefix_length}`}
                          </dd>
                          <dt>Network</dt>
                          <dd>{address.network ?? "Unresolved without prefix"}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p>No usable address was reported.</p>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <p className="details-empty">
              Network interfaces are unavailable. Configure the explicit eth1 and
              eth2 fallback in Settings if subnet assignment is required.
            </p>
          )}
        </section>
      )}

      <section className="details-section">
        <h3>Observation</h3>
        <dl className="details-grid">
          <DetailRow
            label="Last seen"
            value={formatTimestamp(node.last_seen_at, "Not reported")}
          />
          <DetailRow
            label="Last status change"
            value={formatTimestamp(node.last_status_change_at, "Not reported")}
          />
        </dl>
      </section>

      {subchannels.length > 0 && (
        <section className="details-section">
          <h3>Subchannels</h3>
          <div className="subchannel-list">
            {subchannels.map((channel) => (
              <div key={channel.name}>
                <span>
                  <strong>{channel.name}</strong>
                  {channel.reason && <small>{channel.reason}</small>}
                </span>
                <StatusBadge status={channel.status} compact />
              </div>
            ))}
          </div>
        </section>
      )}

      {safeMetadata.length > 0 && (
        <section className="details-section">
          <h3>System information</h3>
          <dl className="metadata-list">
            {safeMetadata.map(([key, value]) => (
              <div key={key}>
                <dt>{key.replaceAll("_", " ")}</dt>
                <dd>{renderMetadataValue(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
    </aside>
  );
}
