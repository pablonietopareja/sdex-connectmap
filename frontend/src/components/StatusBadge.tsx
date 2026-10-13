import { STATUS_LABELS } from "../constants";
import type { ConnectionStatus } from "../types";

export function StatusBadge({
  status,
  compact = false,
}: {
  status: ConnectionStatus;
  compact?: boolean;
}) {
  return (
    <span
      className={`status-badge status-${status}${compact ? " is-compact" : ""}`}
      data-testid={`status-${status}`}
    >
      <span className="status-symbol" aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  );
}
