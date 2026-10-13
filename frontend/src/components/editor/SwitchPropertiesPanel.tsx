import { useEffect, useState, type FormEvent } from "react";
import { CloseIcon } from "../icons";
import { Notice } from "../Notice";
import type {
  SwitchElementView,
  SwitchPropertiesUpdate,
} from "./types";

export interface SwitchPropertiesPanelProps {
  visualSwitch: SwitchElementView | null;
  busy?: boolean;
  onClose: () => void;
  onSave: (
    switchId: string,
    update: SwitchPropertiesUpdate,
  ) => Promise<void>;
  onDelete: (
    switchId: string,
    options?: { leaveUnrouted?: boolean },
  ) => Promise<void>;
}

function operationMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function SwitchPropertiesPanel({
  visualSwitch,
  busy = false,
  onClose,
  onSave,
  onDelete,
}: SwitchPropertiesPanelProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [externalInterface, setExternalInterface] = useState<
    SwitchPropertiesUpdate["external_interface"]
  >(null);
  const [localBusy, setLocalBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!visualSwitch) return;
    setName(visualSwitch.name);
    setDescription(visualSwitch.description ?? "");
    setExternalInterface(visualSwitch.external_interface);
    setError(null);
    setConfirmDelete(false);
  }, [visualSwitch]);

  useEffect(() => {
    if (!visualSwitch) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose, visualSwitch]);

  if (!visualSwitch) return null;
  const isBusy = busy || localBusy;
  const invalid = name.trim().length === 0;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (invalid) return;
    setLocalBusy(true);
    setError(null);
    try {
      await onSave(visualSwitch.id, {
        name: name.trim(),
        description: description.trim() || null,
        external_interface: externalInterface,
      });
    } catch (nextError) {
      setError(operationMessage(nextError, "The Switch could not be saved."));
    } finally {
      setLocalBusy(false);
    }
  };

  const remove = async (leaveUnrouted: boolean) => {
    setLocalBusy(true);
    setError(null);
    try {
      await onDelete(visualSwitch.id, { leaveUnrouted });
      setConfirmDelete(false);
    } catch (nextError) {
      setError(operationMessage(nextError, "The Switch could not be deleted."));
    } finally {
      setLocalBusy(false);
    }
  };

  return (
    <aside
      className="visual-properties-drawer"
      role="dialog"
      aria-modal="false"
      aria-labelledby="switch-properties-title"
      data-testid="switch-properties-panel"
    >
      <header className="visual-properties-header">
        <div>
          <span>ConnectMap topology element</span>
          <h2 id="switch-properties-title">Switch properties</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          aria-label="Close Switch properties"
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </header>

      <form className="visual-properties-form" onSubmit={(event) => void submit(event)}>
        <p className="visual-element-disclaimer">
          This is a ConnectMap topology element. It does not assert device telemetry and is never written to SDEX.
        </p>
        {visualSwitch.aggregate && (
          <section className="rack-aggregate-summary" aria-label="Aggregate Switch status">
            <div>
              <span>Aggregate state</span>
              <strong data-status={visualSwitch.aggregate.status}>
                {visualSwitch.aggregate.status}
              </strong>
            </div>
            <p>
              {visualSwitch.aggregate.connected} connected, {visualSwitch.aggregate.disconnected} disconnected, {visualSwitch.aggregate.unknown} unknown, {visualSwitch.aggregate.disabled} disabled
              {(visualSwitch.aggregate.degraded ?? 0) > 0
                ? `, ${String(visualSwitch.aggregate.degraded)} degraded`
                : ""}
            </p>
          </section>
        )}
        {visualSwitch.interface_conflict && (
          <Notice tone="warning" title="Interface conflict">
            Downstream connections use both eth1 and eth2. Select an explicit SDEX interface for this visual uplink.
          </Notice>
        )}
        <label className="form-field">
          <span>Name</span>
          <input
            value={name}
            maxLength={120}
            required
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>Optional description</span>
          <textarea
            value={description}
            maxLength={500}
            rows={4}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>Associated SDEX interface</span>
          <select
            value={externalInterface ?? ""}
            onChange={(event) => {
              const value = event.target.value;
              setExternalInterface(
                value === "eth1" || value === "eth2" ? value : null,
              );
            }}
          >
            <option value="">Not selected</option>
            <option value="eth1">eth1</option>
            <option value="eth2">eth2</option>
          </select>
        </label>

        {error && <Notice tone="danger">{error}</Notice>}
        {confirmDelete && (
          <Notice tone="danger" title="Delete this Switch?">
            <p>
              Connected source elements remain intact. Choose whether they
              reconnect directly to SDEX or remain temporarily without a
              visual route.
            </p>
            <div className="inline-confirm-actions">
              <button
                className="button button-ghost"
                type="button"
                disabled={isBusy}
                onClick={() => setConfirmDelete(false)}
              >
                Cancel
              </button>
              <button
                className="button button-ghost"
                type="button"
                disabled={isBusy}
                onClick={() => void remove(true)}
              >
                Leave without visual route
              </button>
              <button
                className="button button-danger"
                type="button"
                disabled={isBusy}
                onClick={() => void remove(false)}
              >
                Delete and reconnect
              </button>
            </div>
          </Notice>
        )}

        <footer className="visual-properties-actions">
          <button
            className="button button-danger"
            type="button"
            disabled={isBusy}
            onClick={() => setConfirmDelete(true)}
          >
            Delete Switch
          </button>
          <button
            className="button button-primary"
            type="submit"
            disabled={isBusy || invalid}
          >
            {isBusy ? "Saving…" : "Save Switch"}
          </button>
        </footer>
      </form>
    </aside>
  );
}
