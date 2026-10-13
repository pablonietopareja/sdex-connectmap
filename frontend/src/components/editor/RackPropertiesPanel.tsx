import { useEffect, useMemo, useState, type FormEvent } from "react";
import { CloseIcon } from "../icons";
import { Notice } from "../Notice";
import type {
  RackElementView,
  RackPropertiesUpdate,
} from "./types";
import { RACK_MAX_DIMENSION, RACK_MIN_DIMENSION } from "../nodes/rackGeometry";

export interface RackPropertiesPanelProps {
  rack: RackElementView | null;
  memberNames?: Readonly<Record<string, string>>;
  busy?: boolean;
  onClose: () => void;
  onSave: (
    rackId: string,
    update: RackPropertiesUpdate,
    options: { expelOverflow: boolean },
  ) => Promise<void>;
  onUngroupAll: (rackId: string) => Promise<void>;
  onDelete: (rackId: string) => Promise<void>;
}

function operationMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function clampDimension(value: number): number {
  if (!Number.isFinite(value)) return RACK_MIN_DIMENSION;
  return Math.min(
    RACK_MAX_DIMENSION,
    Math.max(RACK_MIN_DIMENSION, Math.floor(value)),
  );
}

export function RackPropertiesPanel({
  rack,
  memberNames = {},
  busy = false,
  onClose,
  onSave,
  onUngroupAll,
  onDelete,
}: RackPropertiesPanelProps) {
  const [name, setName] = useState("");
  const [rows, setRows] = useState(1);
  const [columns, setColumns] = useState(3);
  const [externalInterface, setExternalInterface] = useState<
    RackPropertiesUpdate["external_interface"]
  >(null);
  const [localBusy, setLocalBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmShrink, setConfirmShrink] = useState(false);
  const [confirmUngroup, setConfirmUngroup] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!rack) return;
    setName(rack.name);
    setRows(rack.rows);
    setColumns(rack.columns);
    setExternalInterface(rack.external_interface);
    setError(null);
    setConfirmShrink(false);
    setConfirmUngroup(false);
    setConfirmDelete(false);
  }, [rack]);

  useEffect(() => {
    if (!rack) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose, rack]);

  const occupied = rack?.member_ids.length ?? 0;
  const nextRows = clampDimension(rows);
  const nextColumns = clampDimension(columns);
  const capacity = nextRows * nextColumns;
  const hasOutOfBoundsMember =
    rack?.slot_assignments.some(
      (slot) => slot.row >= nextRows || slot.column >= nextColumns,
    ) ?? false;
  const requiresShrinkConfirmation =
    capacity < occupied || hasOutOfBoundsMember;
  const available = Math.max(0, capacity - occupied);
  const memberLabels = useMemo(
    () =>
      (rack?.member_ids ?? []).map((memberId) => ({
        id: memberId,
        label: memberNames[memberId] ?? memberId,
      })),
    [memberNames, rack?.member_ids],
  );
  const invalid = name.trim().length === 0;
  const isBusy = busy || localBusy;

  if (!rack) return null;

  const update: RackPropertiesUpdate = {
    name: name.trim(),
    rows: nextRows,
    columns: nextColumns,
    external_interface: externalInterface,
  };

  const save = async (expelOverflow: boolean) => {
    setLocalBusy(true);
    setError(null);
    try {
      await onSave(rack.id, update, { expelOverflow });
      setConfirmShrink(false);
    } catch (nextError) {
      setError(operationMessage(nextError, "The Rack could not be saved."));
    } finally {
      setLocalBusy(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (invalid) return;
    if (requiresShrinkConfirmation) {
      setConfirmShrink(true);
      return;
    }
    void save(false);
  };

  const ungroup = async () => {
    setLocalBusy(true);
    setError(null);
    try {
      await onUngroupAll(rack.id);
      setConfirmUngroup(false);
    } catch (nextError) {
      setError(operationMessage(nextError, "Rack members could not be ungrouped."));
    } finally {
      setLocalBusy(false);
    }
  };

  const remove = async () => {
    setLocalBusy(true);
    setError(null);
    try {
      await onDelete(rack.id);
      setConfirmDelete(false);
    } catch (nextError) {
      setError(operationMessage(nextError, "The Rack could not be deleted."));
    } finally {
      setLocalBusy(false);
    }
  };

  return (
    <aside
      className="visual-properties-drawer"
      role="dialog"
      aria-modal="false"
      aria-labelledby="rack-properties-title"
      data-testid="rack-properties-panel"
    >
      <header className="visual-properties-header">
        <div>
          <span>ConnectMap topology element</span>
          <h2 id="rack-properties-title">Rack properties</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          aria-label="Close Rack properties"
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </header>

      <form className="visual-properties-form" onSubmit={submit}>
        <label className="form-field">
          <span>Name</span>
          <input
            value={name}
            maxLength={120}
            required
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <div className="visual-properties-two-columns">
          <label className="form-field">
            <span>Rows</span>
            <input
              type="number"
              min={RACK_MIN_DIMENSION}
              max={RACK_MAX_DIMENSION}
              value={rows}
              onChange={(event) => setRows(Number(event.target.value))}
            />
          </label>
          <label className="form-field">
            <span>Columns</span>
            <input
              type="number"
              min={RACK_MIN_DIMENSION}
              max={RACK_MAX_DIMENSION}
              value={columns}
              onChange={(event) => setColumns(Number(event.target.value))}
            />
          </label>
        </div>
        <label className="form-field">
          <span>External interface</span>
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

        <dl className="visual-properties-stats">
          <div>
            <dt>Capacity</dt>
            <dd>{capacity}</dd>
          </div>
          <div>
            <dt>Occupied</dt>
            <dd>{occupied}</dd>
          </div>
          <div>
            <dt>Available</dt>
            <dd>{available}</dd>
          </div>
        </dl>

        {rack.aggregate && (
          <section className="rack-aggregate-summary" aria-label="Aggregate Rack status">
            <div>
              <span>Aggregate state</span>
              <strong data-status={rack.aggregate.status}>
                {rack.aggregate.status}
              </strong>
            </div>
            <p>
              {rack.aggregate.connected} connected, {rack.aggregate.disconnected}{" "}
              disconnected, {rack.aggregate.unknown} unknown, {rack.aggregate.disabled}{" "}
              disabled
              {typeof rack.aggregate.degraded === "number"
                ? `, ${String(rack.aggregate.degraded)} degraded`
                : ""}
              {(rack.aggregate.missing ?? 0) > 0
                ? `, ${String(rack.aggregate.missing)} missing`
                : ""}
            </p>
          </section>
        )}

        <section className="visual-member-section">
          <h3>Members</h3>
          {memberLabels.length > 0 ? (
            <ul>
              {memberLabels.map((member) => (
                <li key={member.id} title={member.id}>
                  {member.label}
                </li>
              ))}
            </ul>
          ) : (
            <p>This Rack has no members.</p>
          )}
        </section>

        {error && <Notice tone="danger">{error}</Notice>}
        {confirmShrink && (
          <Notice tone="warning" title="Members fall outside the new layout">
            <p>No connection will be deleted. Members outside the resized Rack must be expelled to the canvas.</p>
            <div className="inline-confirm-actions">
              <button
                className="button button-ghost"
                type="button"
                disabled={isBusy}
                onClick={() => setConfirmShrink(false)}
              >
                Cancel
              </button>
              <button
                className="button button-secondary"
                type="button"
                disabled={isBusy}
                onClick={() => void save(true)}
              >
                Expel overflow and save
              </button>
            </div>
          </Notice>
        )}
        {confirmUngroup && (
          <Notice tone="warning" title="Ungroup all members?">
            <p>Connections will return to the canvas and remain in SDEX.</p>
            <div className="inline-confirm-actions">
              <button
                className="button button-ghost"
                type="button"
                disabled={isBusy}
                onClick={() => setConfirmUngroup(false)}
              >
                Cancel
              </button>
              <button
                className="button button-secondary"
                type="button"
                disabled={isBusy}
                onClick={() => void ungroup()}
              >
                Ungroup all
              </button>
            </div>
          </Notice>
        )}
        {confirmDelete && (
          <Notice tone="danger" title="Delete this Rack?">
            <p>Only the visual Rack is deleted. Its connections remain in SDEX.</p>
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
                className="button button-danger"
                type="button"
                disabled={isBusy}
                onClick={() => void remove()}
              >
                Delete Rack
              </button>
            </div>
          </Notice>
        )}

        <footer className="visual-properties-actions">
          <button
            className="button button-ghost"
            type="button"
            disabled={isBusy || occupied === 0}
            onClick={() => setConfirmUngroup(true)}
          >
            Ungroup all
          </button>
          <button
            className="button button-danger"
            type="button"
            disabled={isBusy}
            onClick={() => setConfirmDelete(true)}
          >
            Delete Rack
          </button>
          <button
            className="button button-primary"
            type="submit"
            disabled={isBusy || invalid}
          >
            {isBusy ? "Saving…" : "Save Rack"}
          </button>
        </footer>
      </form>
    </aside>
  );
}
