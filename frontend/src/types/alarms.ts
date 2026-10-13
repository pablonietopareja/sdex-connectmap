export const ALARM_SEVERITIES = ["info", "warning", "error"] as const;

export type AlarmSeverity = (typeof ALARM_SEVERITIES)[number];

/**
 * A current, user-facing condition derived from ConnectMap state.
 *
 * `id` is a semantic identity, not an event identifier. Repeated refreshes of
 * the same condition therefore remain one alarm instead of growing a queue.
 */
export interface TopologyAlarm {
  id: string;
  severity: AlarmSeverity;
  title: string;
  description: string;
  timestamp?: string | null;
  /** Timestamp name used by the backend topology contract. */
  occurred_at?: string | null;
  source?: string | null;
}

export interface AlarmDerivationOptions {
  /** True only for a real SDEX session explicitly started without TLS checks. */
  tlsVerificationDisabled?: boolean;
}
