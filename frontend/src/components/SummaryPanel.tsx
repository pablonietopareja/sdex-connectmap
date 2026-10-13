import { CONNECTION_PRESENTATION } from "../constants";
import type { ConnectionType, TopologySummary } from "../types";

const TYPE_ORDER: ConnectionType[] = [
  "siemens_s7_1200_1500",
  "siemens_s7_300_400",
  "rockwell_allen_bradley",
  "modbus",
  "sinumerik_840d",
  "fanuc_cnc",
  "opcua_remote_server",
  "opcua_local_endpoint",
  "mqtt_broker",
];

export function SummaryPanel({
  summary,
  collapsed,
  onToggle,
}: {
  summary: TopologySummary;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <aside
      className={`summary-panel${collapsed ? " is-collapsed" : ""}`}
      aria-label="Topology summary"
    >
      <button
        className="summary-heading"
        type="button"
        aria-expanded={!collapsed}
        onClick={onToggle}
      >
        <span>
          <small>Topology</small>
          <strong>{summary.total_configured} configured</strong>
        </span>
        <span className="summary-collapse-icon" aria-hidden="true">
          {collapsed ? "+" : "−"}
        </span>
      </button>
      {!collapsed && (
        <div className="summary-body">
          <div className="summary-primary">
            <div>
              <span>Total</span>
              <strong>{summary.total_configured}</strong>
            </div>
            <div>
              <span>Enabled</span>
              <strong>{summary.enabled}</strong>
            </div>
          </div>
          <div className="summary-statuses">
            <div className="summary-status connected">
              <span aria-hidden="true" />
              <small>Connected</small>
              <strong>{summary.connected}</strong>
            </div>
            <div className="summary-status disconnected">
              <span aria-hidden="true" />
              <small>Disconnected</small>
              <strong>{summary.disconnected}</strong>
            </div>
            <div className="summary-status disabled">
              <span aria-hidden="true" />
              <small>Disabled</small>
              <strong>{summary.disabled}</strong>
            </div>
            <div className="summary-status unknown">
              <span aria-hidden="true" />
              <small>Unknown / degraded</small>
              <strong>{summary.unknown_degraded}</strong>
            </div>
          </div>
          <div className="summary-types">
            <p>By connection type</p>
            {TYPE_ORDER.map((type) => (
              <div key={type}>
                <span>{CONNECTION_PRESENTATION[type].shortLabel}</span>
                <strong>{summary.by_type[type] ?? 0}</strong>
              </div>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}
