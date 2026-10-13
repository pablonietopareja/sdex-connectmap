import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type { AlarmSeverity, TopologyAlarm } from "../types";
import { formatTimestamp } from "../utils";
import { deduplicateAlarms } from "../utils/alarms";
import { AlertIcon, InfoIcon } from "./icons";

interface AlarmsMenuProps {
  alarms: readonly TopologyAlarm[];
  className?: string;
}

const severityLabel: Record<AlarmSeverity, string> = {
  info: "Information",
  warning: "Warning",
  error: "Error",
};

function AlarmSeverityIcon({ severity }: { severity: AlarmSeverity }) {
  return severity === "info" ? <InfoIcon /> : <AlertIcon />;
}

/**
 * Compact, read-only alarm centre. A dialog/list is used instead of ARIA menu
 * semantics because alarms are information rather than executable commands.
 */
export function AlarmsMenu({ alarms, className = "" }: AlarmsMenuProps) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLLIElement | null>>([]);
  const [open, setOpen] = useState(false);
  const uniqueAlarms = useMemo(() => deduplicateAlarms(alarms), [alarms]);
  const highestSeverity = uniqueAlarms[0]?.severity ?? "info";

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const firstItem = itemRefs.current[0];
    if (firstItem) firstItem.focus();
    else popoverRef.current?.focus();
  }, [open]);

  const closeAndRestoreFocus = () => {
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const focusItem = (index: number) => {
    if (uniqueAlarms.length === 0) return;
    const wrapped =
      (index + uniqueAlarms.length) % uniqueAlarms.length;
    itemRefs.current[wrapped]?.focus();
  };

  const onPopoverKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeAndRestoreFocus();
      return;
    }

    const currentIndex = itemRefs.current.findIndex(
      (item) => item === document.activeElement,
    );
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusItem(currentIndex + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusItem(currentIndex < 0 ? uniqueAlarms.length - 1 : currentIndex - 1);
        break;
      case "Home":
        event.preventDefault();
        focusItem(0);
        break;
      case "End":
        event.preventDefault();
        focusItem(uniqueAlarms.length - 1);
        break;
      default:
        break;
    }
  };

  const openFromKeyboard = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div
      ref={rootRef}
      className={`alarms-menu${open ? " is-open" : ""}${className ? ` ${className}` : ""}`}
    >
      <button
        ref={triggerRef}
        type="button"
        className="alarms-menu-trigger"
        data-severity={highestSeverity}
        data-has-alarms={uniqueAlarms.length > 0}
        aria-label={`Alarms, ${uniqueAlarms.length} active`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={`${id}-popover`}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={openFromKeyboard}
      >
        <AlertIcon />
        <span className="alarms-menu-trigger-word">Alarms</span>
        <span className="alarms-menu-count" aria-hidden="true">
          {uniqueAlarms.length}
        </span>
      </button>

      {open && (
        <div
          ref={popoverRef}
          id={`${id}-popover`}
          className="alarms-menu-popover"
          role="dialog"
          aria-modal="false"
          aria-labelledby={`${id}-title`}
          tabIndex={-1}
          onKeyDown={onPopoverKeyDown}
        >
          <div className="alarms-menu-header">
            <div>
              <strong id={`${id}-title`}>Active alarms</strong>
              <span>
                {uniqueAlarms.length} current condition
                {uniqueAlarms.length === 1 ? "" : "s"}
              </span>
            </div>
          </div>

          <div className="alarms-menu-scroll">
            {uniqueAlarms.length === 0 ? (
              <p className="alarms-menu-empty">No active alarms.</p>
            ) : (
              <ul className="alarms-list" aria-label="Active alarms">
                {uniqueAlarms.map((alarm, index) => (
                  <li
                    ref={(element) => {
                      itemRefs.current[index] = element;
                    }}
                    key={alarm.id}
                    className="alarm-list-item"
                    data-severity={alarm.severity}
                    tabIndex={-1}
                    aria-describedby={`${id}-alarm-${index}-description`}
                  >
                    <span className="alarm-list-icon" aria-hidden="true">
                      <AlarmSeverityIcon severity={alarm.severity} />
                    </span>
                    <div className="alarm-list-copy">
                      <span className="alarm-severity-label">
                        {severityLabel[alarm.severity]}
                      </span>
                      <strong>{alarm.title}</strong>
                      <p id={`${id}-alarm-${index}-description`}>
                        {alarm.description}
                      </p>
                      {(alarm.source || alarm.timestamp) && (
                        <div className="alarm-list-meta">
                          {alarm.source && <span>Source: {alarm.source}</span>}
                          {alarm.timestamp && (
                            <time dateTime={alarm.timestamp}>
                              {formatTimestamp(alarm.timestamp)}
                            </time>
                          )}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
