import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CONNECTION_PRESENTATION } from "../../constants";
import { displayAddress, nodeIcon } from "../../utils";
import type { ConnectionFlowNode } from "../canvas/types";
import { EditIcon } from "../icons";
import { StatusBadge } from "../StatusBadge";

function ConnectionNodeCardComponent({
  data,
  selected,
}: NodeProps<ConnectionFlowNode>) {
  const node = data.connection;
  const presentation = CONNECTION_PRESENTATION[node.type];
  const embedded = data.variant === "embedded";

  return (
    <article
      className={[
        "connection-node-card",
        `node-status-${node.status}`,
        node.enabled ? "" : "node-disabled",
        node.stale ? "node-stale" : "",
        embedded ? "is-embedded" : "",
        selected ? "selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      role="button"
      tabIndex={0}
      aria-label={`${node.display_name}, ${presentation.label}, ${node.status}. Double-click for details`}
      data-testid={`connection-node-${node.type}`}
      data-variant={embedded ? "embedded" : "standalone"}
      onDoubleClick={(event) => {
        event.stopPropagation();
        data.onOpen(node);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          data.onOpen(node);
        }
      }}
    >
      {!embedded && (
        <>
          <Handle id="left" type="source" position={Position.Left} aria-label="Reconnect cable from the left side" />
          <Handle id="right" type="source" position={Position.Right} aria-label="Reconnect cable from the right side" />
          <Handle id="top" type="source" position={Position.Top} aria-label="Reconnect cable from the top side" />
          <Handle id="bottom" type="source" position={Position.Bottom} aria-label="Reconnect cable from the bottom side" />
        </>
      )}
      <div className="node-accent" aria-hidden="true" />
      <header className="node-header">
        <strong title={node.display_name}>{node.display_name}</strong>
      </header>
      <div className="node-main">
        <div className="node-icon-shell">
          <img
            src={nodeIcon(node)}
            alt=""
            draggable={false}
            loading="eager"
          />
        </div>
        <div className="node-copy">
          <dl className="node-facts">
            <div>
              <dt>Address</dt>
              <dd title={displayAddress(node)}>{displayAddress(node)}</dd>
            </div>
            <div>
              <dt>Subtype</dt>
              <dd title={node.subtype || presentation.label}>
                {node.subtype || presentation.label}
              </dd>
            </div>
          </dl>
          <div className="node-status-area">
            <StatusBadge
              status={node.enabled ? node.status : "disabled"}
              compact
            />
            {data.editorEnabled && (
              <span
                className="node-edit-hint"
                aria-label="Movable in Editor mode"
              >
                <EditIcon />
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

export const ConnectionNodeCard = memo(ConnectionNodeCardComponent);
