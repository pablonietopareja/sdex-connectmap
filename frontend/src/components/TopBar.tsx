import { useEffect, useId, useRef, useState } from "react";
import { CONNECTION_PRESENTATION, REFRESH_OPTIONS, THEMES } from "../constants";
import type {
  ConnectionStatus,
  ThemePreference,
  TopologySnapshot,
} from "../types";
import { formatTimestamp } from "../utils";
import { deriveTopologyAlarms } from "../utils/alarms";
import { AlarmsMenu } from "./AlarmsMenu";
import { Switch } from "./Switch";
import {
  ChevronDownIcon,
  InfoIcon,
  MonitorIcon,
  MoonIcon,
  RefreshIcon,
  SettingsIcon,
  SunIcon,
} from "./icons";
import { SelectMenu } from "./SelectMenu";

const gatewayStatusCopy: Record<ConnectionStatus, string> = {
  connected: "SDEX online",
  disconnected: "SDEX unavailable",
  disabled: "SDEX unavailable",
  unlicensed: "License issue",
  degraded: "SDEX degraded",
  unknown: "SDEX status unknown",
};

function ThemeIcon({ preference }: { preference: ThemePreference }) {
  if (preference === "light") return <SunIcon />;
  if (preference === "dark") return <MoonIcon />;
  return <MonitorIcon />;
}

interface StatusDetailsMenuProps {
  mockMode: boolean;
  partial: boolean;
  updated: string;
  eventsConnected: boolean;
}

function StatusDetailsMenu({
  mockMode,
  partial,
  updated,
  eventsConnected,
}: StatusDetailsMenuProps) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;

    const closeOnPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      requestAnimationFrame(() => triggerRef.current?.focus());
    };

    document.addEventListener("pointerdown", closeOnPointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div
      ref={rootRef}
      className={`status-details-menu${open ? " is-open" : ""}`}
    >
      <button
        ref={triggerRef}
        type="button"
        className="status-details-trigger"
        aria-label="SDEX status details"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={`${id}-popover`}
        title="SDEX status details"
        onClick={() => setOpen((current) => !current)}
      >
        <InfoIcon />
        <span className="status-details-trigger-word">Status</span>
        <ChevronDownIcon />
      </button>
      {open && (
        <div
          id={`${id}-popover`}
          className="status-details-popover"
          role="dialog"
          aria-label="SDEX status details"
        >
          <strong>SDEX status details</strong>
          <dl>
            <div>
              <dt>Data source</dt>
              <dd>{mockMode ? "Mock Mode" : "Real SDEX"}</dd>
            </div>
            <div>
              <dt>Discovery</dt>
              <dd>{partial ? "Partial discovery" : "Complete"}</dd>
            </div>
            <div>
              <dt>Last update</dt>
              <dd>{updated}</dd>
            </div>
            <div>
              <dt>Live updates</dt>
              <dd>{eventsConnected ? "Connected" : "Reconnecting"}</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}

interface TopBarProps {
  snapshot: TopologySnapshot;
  editorEnabled: boolean;
  showNotEnabled: boolean;
  refreshInterval: number;
  theme: ThemePreference;
  eventsConnected: boolean;
  tlsWarning: boolean;
  onEditorChange: (enabled: boolean) => void;
  onShowNotEnabledChange: (enabled: boolean) => void;
  onRefreshIntervalChange: (seconds: number) => void;
  onThemeChange: (theme: ThemePreference) => void;
  onRefresh: () => void;
  onOpenSettings: () => void;
}

export function TopBar({
  snapshot,
  editorEnabled,
  showNotEnabled,
  refreshInterval,
  theme,
  eventsConnected,
  tlsWarning,
  onEditorChange,
  onShowNotEnabledChange,
  onRefreshIntervalChange,
  onThemeChange,
  onRefresh,
  onOpenSettings,
}: TopBarProps) {
  const status = snapshot.stale ? "unknown" : snapshot.gateway.status;
  const alarms = deriveTopologyAlarms(snapshot, {
    tlsVerificationDisabled: tlsWarning,
  });
  const updated = formatTimestamp(snapshot.last_successful_refresh);
  const statusCopy = snapshot.stale
    ? "Showing cached data"
    : gatewayStatusCopy[status];

  return (
    <header className="top-bar">
      <div className="brand" data-testid="topbar-brand">
        <img
          className="brand-logo"
          src="/icons/SDEX_ConnectMap_logo.svg"
          alt=""
          draggable={false}
        />
        <div>
          <strong>SDEX ConnectMap</strong>
          <span>by Pablo</span>
        </div>
      </div>

      <div className="topbar-status" data-testid="topbar-status">
        <div
          className="gateway-health"
          data-status={status}
          title={`${statusCopy}. Updated ${updated}. ${
            eventsConnected
              ? "Live updates connected"
              : "Live update stream reconnecting"
          }.`}
        >
          <span className="health-symbol" aria-hidden="true" />
          <div>
            <strong>{statusCopy}</strong>
            <span title={snapshot.last_successful_refresh ?? undefined}>
              Updated {updated}
            </span>
          </div>
          <span
            className={`events-indicator${eventsConnected ? " connected" : ""}`}
            title={
              eventsConnected
                ? "Live updates connected"
                : "Live update stream reconnecting"
            }
            aria-label={
              eventsConnected
                ? "Live updates connected"
                : "Live update stream reconnecting"
            }
          />
        </div>

        <div className="secondary-status-inline">
          <span
            className={snapshot.mock_mode ? "mock-badge" : "real-sdex-badge"}
            title={
              snapshot.mock_mode
                ? "No real SDEX data is being used"
                : "Using data from the configured real SDEX system"
            }
            aria-label={
              snapshot.mock_mode
                ? "Data source: Mock Mode"
                : "Data source: Real SDEX"
            }
          >
            {snapshot.mock_mode ? "Mock Mode" : "Real SDEX"}
          </span>
          {snapshot.partial && (
            <span
              className="partial-badge"
              title="One or more modules could not be read"
            >
              Partial discovery
            </span>
          )}
        </div>

        <StatusDetailsMenu
          mockMode={snapshot.mock_mode}
          partial={snapshot.partial}
          updated={updated}
          eventsConnected={eventsConnected}
        />
        <AlarmsMenu alarms={alarms} />
      </div>

      <div className="top-controls topbar-actions" data-testid="topbar-actions">

        <span
          className="topbar-select-wrap refresh-select-wrap"
          title={`Refresh interval: ${
            REFRESH_OPTIONS.find((option) => option.value === refreshInterval)
              ?.label ?? refreshInterval
          }`}
        >
          <SelectMenu
            ariaLabel="Refresh interval"
            className="refresh-select"
            value={refreshInterval}
            options={REFRESH_OPTIONS}
            onChange={onRefreshIntervalChange}
          />
        </span>

        <button
          className="button button-secondary refresh-button"
          type="button"
          onClick={onRefresh}
          disabled={snapshot.refresh_in_progress}
          aria-busy={snapshot.refresh_in_progress}
          title={snapshot.refresh_in_progress ? "Refreshing topology" : "Refresh now"}
        >
          <RefreshIcon className={snapshot.refresh_in_progress ? "spin" : ""} />
          <span>
            {snapshot.refresh_in_progress ? "Refreshing…" : "Refresh now"}
          </span>
        </button>

        <div className="top-switches">
          <span className="top-switch-item" title="Editor mode">
            <Switch
              checked={editorEnabled}
              onChange={onEditorChange}
              label="Editor"
            />
          </span>
          <span
            className="top-switch-item"
            title="Show connections that are not enabled"
          >
            <Switch
              checked={showNotEnabled}
              onChange={onShowNotEnabledChange}
              label="Show not enabled"
            />
          </span>
        </div>

        <span
          className="topbar-select-wrap theme-select-wrap"
          title={`Theme: ${theme}`}
        >
          <SelectMenu
            ariaLabel="Theme"
            className="theme-select"
            value={theme}
            options={THEMES.map((value) => ({
              value,
              label: `${value[0]?.toUpperCase()}${value.slice(1)}`,
            }))}
            leading={<ThemeIcon preference={theme} />}
            onChange={onThemeChange}
          />
        </span>

        <button
          className="icon-button settings-button"
          type="button"
          aria-label="Settings"
          title="Settings"
          onClick={onOpenSettings}
        >
          <SettingsIcon />
        </button>
      </div>
    </header>
  );
}

export function topologyTypeLabel(type: keyof TopologySnapshot["summary"]["by_type"]) {
  return CONNECTION_PRESENTATION[type]?.shortLabel ?? type;
}
