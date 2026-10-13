import { memo, type CSSProperties } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { StatusBadge } from "../StatusBadge";
import type { RackNodeViewData, RackSlotView } from "../editor/types";
import {
  EMBEDDED_CONNECTION_HEIGHT,
  EMBEDDED_CONNECTION_WIDTH,
  RACK_MAX_DIMENSION,
  RACK_MIN_DIMENSION,
  RACK_SLOT_GAP,
  rackDimensions,
  rackSlotKey,
} from "./rackGeometry";

export {
  EMBEDDED_CONNECTION_HEIGHT,
  EMBEDDED_CONNECTION_WIDTH,
  RACK_CONTENT_PADDING_TOP,
  RACK_FOOTER_HEIGHT,
  RACK_HEADER_HEIGHT,
  RACK_MAX_DIMENSION,
  RACK_MIN_DIMENSION,
  RACK_PADDING_X,
  RACK_SLOT_GAP,
  rackDimensions,
  rackSlotKey,
  rackSlotPosition,
} from "./rackGeometry";

export type RackFlowNode = Node<RackNodeViewData, "rack">;

interface RackStyle extends CSSProperties {
  "--rack-columns": number;
  "--rack-rows": number;
  "--rack-slot-width": string;
  "--rack-slot-height": string;
  "--rack-slot-gap": string;
}

function safeDimension(value: number): number {
  if (!Number.isFinite(value)) return RACK_MIN_DIMENSION;
  return Math.min(
    RACK_MAX_DIMENSION,
    Math.max(RACK_MIN_DIMENSION, Math.floor(value)),
  );
}

function RackNodeCardComponent({
  data,
  selected,
}: NodeProps<RackFlowNode>) {
  const { rack } = data;
  const rows = safeDimension(rack.rows);
  const columns = safeDimension(rack.columns);
  const dimensions = rackDimensions(rows, columns);
  const assignments = new Map(
    rack.slot_assignments.map((slot) => [rackSlotKey(slot.row, slot.column), slot]),
  );
  const missingMembers = new Set(data.missingMemberIds ?? []);
  const highlightedKey = data.highlightedSlot
    ? rackSlotKey(data.highlightedSlot.row, data.highlightedSlot.column)
    : null;
  const slots: RackSlotView[] = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      slots.push(
        assignments.get(rackSlotKey(row, column)) ?? {
          row,
          column,
          connection_id: null,
        },
      );
    }
  }
  const occupied = slots.filter((slot) => slot.connection_id !== null).length;
  const style: RackStyle = {
    width: dimensions.width,
    height: dimensions.height,
    "--rack-columns": columns,
    "--rack-rows": rows,
    "--rack-slot-width": `${EMBEDDED_CONNECTION_WIDTH}px`,
    "--rack-slot-height": `${EMBEDDED_CONNECTION_HEIGHT}px`,
    "--rack-slot-gap": `${RACK_SLOT_GAP}px`,
  };

  return (
    <article
      className={[
        "rack-node-card",
        `node-status-${data.aggregateStatus}`,
        selected ? "selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={style}
      role="button"
      tabIndex={0}
      aria-label={`${rack.name}, Rack, ${occupied} of ${rows * columns} slots occupied. Double-click for properties`}
      data-testid="rack-node"
      onDoubleClick={(event) => {
        event.stopPropagation();
        data.onOpen(rack);
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        data.onOpen(rack);
      }}
    >
      <Handle
        id="rack-left"
        type="source"
        position={Position.Left}
        aria-label="Rack left uplink"
      />
      <Handle
        id="rack-right"
        type="source"
        position={Position.Right}
        aria-label="Rack right uplink"
      />
      <div className="rack-node-accent" aria-hidden="true" />
      <header className="rack-node-header">
        <span>ConnectMap Rack</span>
        <strong title={rack.name}>{rack.name}</strong>
        <small>
          {rows} × {columns}
        </small>
      </header>
      <div className="rack-slot-grid">
        {slots.map((slot) => {
          const key = rackSlotKey(slot.row, slot.column);
          const connectionId = slot.connection_id;
          const highlighted = key === highlightedKey;
          if (connectionId && missingMembers.has(connectionId)) {
            return (
              <div
                className={`rack-slot rack-slot-missing${highlighted ? " is-highlighted" : ""}`}
                key={key}
                data-row={slot.row}
                data-column={slot.column}
                data-connection-id={connectionId}
                role="status"
                title={connectionId}
              >
                <strong>Connection unavailable</strong>
                <span>{connectionId}</span>
                <small>Membership is preserved</small>
              </div>
            );
          }
          if (connectionId) {
            return (
              <div
                className={`rack-slot rack-slot-occupied${highlighted ? " is-highlighted" : ""}`}
                key={key}
                data-row={slot.row}
                data-column={slot.column}
                data-connection-id={connectionId}
                aria-label={`Occupied rack slot ${slot.row + 1}, ${slot.column + 1}`}
              >
                <span className="sr-only">{connectionId}</span>
              </div>
            );
          }
          return (
            <div
              className={`rack-slot rack-slot-empty${highlighted ? " is-highlighted" : ""}`}
              key={key}
              data-row={slot.row}
              data-column={slot.column}
              role="img"
              aria-label={`Empty rack slot ${slot.row + 1}, ${slot.column + 1}. ${
                data.editorEnabled
                  ? "Drop a connection here."
                  : "Enable Editor to assign a connection."
              }`}
              title={
                data.editorEnabled
                  ? "Drop a connection here"
                  : "Enable Editor to assign a connection"
              }
            >
              <span aria-hidden="true">+</span>
              <small>Empty slot</small>
            </div>
          );
        })}
      </div>
      <footer className="rack-node-footer">
        <StatusBadge status={data.aggregateStatus} compact />
        <span title="Connected / disconnected / unknown / disabled">
          {data.aggregateCounts.connected} / {data.aggregateCounts.disconnected} /{" "}
          {data.aggregateCounts.unknown} / {data.aggregateCounts.disabled}
        </span>
        <span>
          {occupied}/{rows * columns} occupied
        </span>
        <strong>{rack.external_interface ?? "Interface not selected"}</strong>
      </footer>
    </article>
  );
}

export const RackNodeCard = memo(RackNodeCardComponent);
